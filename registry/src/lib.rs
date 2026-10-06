//! Curated, bounded registry. The signing authority verifies Geofabrik bytes
//! off-chain; the guest validates the partition and immutable snapshot metadata.
use spel_framework::prelude::*;
use serde::{Deserialize, Serialize};
mod regions;

#[account_type]
#[derive(BorshSerialize, BorshDeserialize, Debug, Clone)]
pub struct RegistryState {
    pub authority: [u8; 32],
    pub entries_json: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Entry {
    pub region: String,
    pub parent: Option<String>,
    pub level: String,
    pub cid: String,
    pub source_url: String,
    pub checksum: String,
    pub version: String,
    pub hosted: bool,
    pub timestamp: u64,
    pub sha256: String,
    pub size: u64,
}

fn invalid(message: impl Into<String>) -> SpelError {
    SpelError::custom(2000, message)
}

fn is_hex(value: &str, length: usize) -> bool {
    value.len() == length && value.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

impl Entry {
    pub fn validate(&self) -> Result<(), SpelError> {
        let (_, parent, level, path) = regions::REGIONS.iter()
            .find(|r| r.0 == self.region).ok_or_else(|| invalid("Region outside frozen partition"))?;
        if self.parent.as_deref() != *parent || self.level != *level {
            return Err(invalid("Wrong parent or level"));
        }
        let prefix = format!("https://download.geofabrik.de/{path}-");
        let suffix = self.source_url.strip_prefix(&prefix)
            .and_then(|s| s.strip_suffix(".osm.pbf"))
            .ok_or_else(|| invalid("Wrong Geofabrik source URL"))?;
        if suffix != "latest" && !(suffix.len() == 6 && suffix.bytes().all(|b| b.is_ascii_digit())) {
            return Err(invalid("Wrong snapshot filename"));
        }
        if !(20..=160).contains(&self.cid.len()) || !self.cid.bytes().all(|b| b.is_ascii_alphanumeric()) {
            return Err(invalid("Invalid CID"));
        }
        if !is_hex(&self.checksum, 32) || !is_hex(&self.sha256, 64) {
            return Err(invalid("Invalid snapshot hashes"));
        }
        use chrono::Datelike;
        let version = chrono::DateTime::parse_from_rfc3339(&self.version)
            .map_err(|_| invalid("Invalid snapshot version"))?;
        if self.version.len() > 40 || !(2000..=2200).contains(&version.year()) {
            return Err(invalid("Invalid snapshot version bounds"));
        }
        if !self.hosted || self.size == 0 || self.timestamp == 0 {
            return Err(invalid("Only nonempty hosted snapshots can be registered"));
        }
        Ok(())
    }
}

/// Atomic transition; run every validation before serializing a post-state.
pub fn apply(state: &RegistryState, signer: &[u8; 32], payload: &[u8], single: bool)
    -> Result<RegistryState, SpelError>
{
    if signer != &state.authority {
        return Err(SpelError::Unauthorized { message: "Registry curator must sign".into() });
    }
    if payload.len() > 100_000 {
        return Err(invalid("Batch exceeds 100 KB"));
    }
    let batch: Vec<Entry> = serde_json::from_slice(payload).map_err(|e| invalid(e.to_string()))?;
    if batch.is_empty() || batch.len() > 72 || (single && batch.len() != 1) {
        return Err(invalid("Expected 1 entry for register or 1–72 entries for batch"));
    }
    let mut entries: Vec<Entry> = serde_json::from_str(&state.entries_json)
        .map_err(|e| invalid(e.to_string()))?;
    let mut seen = std::collections::BTreeSet::new();
    for entry in &batch {
        entry.validate()?;
        if !seen.insert(&entry.region) { return Err(invalid("Duplicate region in batch")); }
        for previous in entries.iter().filter(|e| e.region == entry.region) {
            let same_version = chrono::DateTime::parse_from_rfc3339(&previous.version)
                .map_err(|_| invalid("Corrupt version"))? ==
                chrono::DateTime::parse_from_rfc3339(&entry.version)
                .map_err(|_| invalid("Invalid version"))?;
            if same_version && (previous.cid != entry.cid || previous.checksum != entry.checksum ||
                previous.sha256 != entry.sha256 || previous.size != entry.size) {
                return Err(invalid("A snapshot version cannot change its bytes or CID"));
            }
            if entry.timestamp < previous.timestamp {
                return Err(invalid("Registration timestamp cannot regress"));
            }
        }
    }
    for entry in batch {
        entries.retain(|e| !(e.region == entry.region && e.version == entry.version));
        entries.push(entry);
    }
    // Keep the two newest snapshot versions per region, independent of
    // registration order. Bound account size and avoid an unbounded guest log.
    entries.sort_by(|a, b| {
        let a = chrono::DateTime::parse_from_rfc3339(&a.version).ok();
        let b = chrono::DateTime::parse_from_rfc3339(&b.version).ok();
        b.cmp(&a)
    });
    let mut counts = std::collections::BTreeMap::new();
    entries.retain(|e| {
        let count = counts.entry(e.region.clone()).or_insert(0);
        *count += 1;
        *count <= 2
    });
    entries.sort_by_key(|e| std::cmp::Reverse(e.timestamp));
    let entries_json = serde_json::to_string(&entries).map_err(|e| invalid(e.to_string()))?;
    if entries_json.len() > 102_364 { return Err(invalid("Registry capacity exceeded")); }
    Ok(RegistryState { authority: state.authority, entries_json })
}

#[lez_program]
mod osm_registry {
    #[allow(unused_imports)]
    use super::*;

    #[instruction]
    pub fn initialize(
        #[account(init, pda = literal("osm_registry_v1"))] mut state: AccountWithMetadata,
        #[account(signer)] authority: AccountWithMetadata,
    ) -> SpelResult {
        let value = RegistryState { authority: *authority.account_id.value(), entries_json: "[]".into() };
        state.account.data = borsh::to_vec(&value).map_err(|e| invalid(e.to_string()))?
            .try_into().map_err(|_| invalid("State exceeds account limit"))?;
        Ok(SpelOutput::execute(vec![state, authority], vec![]))
    }

    #[instruction]
    pub fn register(
        #[account(mut, pda = literal("osm_registry_v1"), owner = self_program_id)] mut state: AccountWithMetadata,
        #[account(signer)] authority: AccountWithMetadata,
        payload: String,
    ) -> SpelResult {
        let value = RegistryState::try_from_slice(&state.account.data)
            .map_err(|e| invalid(e.to_string()))?;
        let next = apply(&value, authority.account_id.value(), payload.as_bytes(), true)?;
        state.account.data = borsh::to_vec(&next).map_err(|e| invalid(e.to_string()))?
            .try_into().map_err(|_| invalid("State exceeds account limit"))?;
        Ok(SpelOutput::execute(vec![state, authority], vec![]))
    }

    #[instruction]
    pub fn batch_register(
        #[account(mut, pda = literal("osm_registry_v1"), owner = self_program_id)] mut state: AccountWithMetadata,
        #[account(signer)] authority: AccountWithMetadata,
        payload: String,
    ) -> SpelResult {
        let value = RegistryState::try_from_slice(&state.account.data)
            .map_err(|e| invalid(e.to_string()))?;
        let next = apply(&value, authority.account_id.value(), payload.as_bytes(), false)?;
        state.account.data = borsh::to_vec(&next).map_err(|e| invalid(e.to_string()))?
            .try_into().map_err(|_| invalid("State exceeds account limit"))?;
        Ok(SpelOutput::execute(vec![state, authority], vec![]))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn entry(region: &str, path: &str) -> Entry {
        Entry { region: region.into(), parent: None, level: "country".into(),
            cid: "zDvZRwzkzrrYB6sS1rRpRLt4gBhc1pWoyTSjkfszfmj1seaYYLCZ".into(),
            source_url: format!("https://download.geofabrik.de/{path}-latest.osm.pbf"),
            checksum: "a".repeat(32), sha256: "b".repeat(64),
            version: "2026-10-01T00:00:00Z".into(), timestamp: 1, size: 10, hosted: true }
    }
    fn state() -> RegistryState { RegistryState { authority: [1;32], entries_json: "[]".into() } }
    #[test]
    fn unauthorized_write_rejected() {
        assert!(apply(&state(), &[2;32], b"[]", false).is_err());
    }
    #[test]
    fn batch_atomic_and_partition_enforced() {
        let good = entry("germany", "europe/germany");
        let bad = entry("india", "asia/india");
        assert!(apply(&state(), &[1;32], &serde_json::to_vec(&vec![good.clone(),bad]).unwrap(), false).is_err());
        assert_eq!(state().entries_json, "[]");
        let next = apply(&state(), &[1;32], &serde_json::to_vec(&vec![good]).unwrap(), true).unwrap();
        assert_eq!(serde_json::from_str::<Vec<Entry>>(&next.entries_json).unwrap().len(), 1);
    }
    #[test]
    fn conflicting_snapshot_is_rejected() {
        let good = entry("germany", "europe/germany");
        let next = apply(&state(), &[1;32], &serde_json::to_vec(&vec![good.clone()]).unwrap(), true).unwrap();
        let mut bad = good; bad.sha256 = "c".repeat(64);
        assert!(apply(&next, &[1;32], &serde_json::to_vec(&vec![bad]).unwrap(), true).is_err());
    }
    #[test]
    fn duplicate_region_and_invalid_hash_rejected() {
        let good = entry("germany", "europe/germany");
        assert!(apply(&state(), &[1;32], &serde_json::to_vec(&vec![good.clone(), good.clone()]).unwrap(), false).is_err());
        let mut bad = good; bad.checksum = "x".repeat(32);
        assert!(bad.validate().is_err());
    }
}
