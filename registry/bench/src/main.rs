//! Same executor input shape and cycle accounting as LEZ tools/cycle_bench.
use nssa_core::account::{Account, AccountId, AccountWithMetadata};
use osm_registry::{Entry, Instruction, RegistryState};
use osm_registry_methods::{OSM_REGISTRY_ELF, OSM_REGISTRY_ID};
use risc0_zkvm::{default_executor, ExecutorEnv};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let specs: Vec<serde_json::Value> = serde_json::from_str(include_str!("../../../src/logos_maps/regions.json"))?;
    let signer = [1u8; 32];
    let registry = spel_framework_core::pda::compute_pda_raw(&OSM_REGISTRY_ID, &[b"osm_registry_v1"])?;
    let initial = RegistryState { authority: signer, entries_json: "[]".into() };
    let states = vec![
        AccountWithMetadata { account_id: registry, is_authorized: false, account: Account {
            program_owner: OSM_REGISTRY_ID, data: borsh::to_vec(&initial)?.try_into()?, ..Default::default() } },
        AccountWithMetadata { account_id: AccountId::new(signer), is_authorized: true, account: Account::default() },
    ];
    let mut measurements = Vec::new();
    for count in [1usize, 5, 25, 72] {
        let entries: Vec<Entry> = specs.iter().take(count).map(|s| Entry {
            region: s["region"].as_str().unwrap().into(),
            parent: s["parent"].as_str().map(String::from), level: s["level"].as_str().unwrap().into(),
            cid: "zDvZRwzmAsHGPSv7nbxXFPnWnUtPvRFTVRitqtqAZj6KpxvH3WSY".into(),
            source_url: format!("https://download.geofabrik.de/{}-latest.osm.pbf",s["path"].as_str().unwrap()),
            checksum: "a".repeat(32), sha256: "b".repeat(64), size: 10, timestamp: 1,
            hosted: true, version: "2026-10-01T00:00:00Z".into(),
        }).collect();
        let payload = serde_json::to_string(&entries)?;
        let (name, instruction) = if count == 1 { ("register", Instruction::Register { payload }) }
            else { ("batch_register", Instruction::BatchRegister { payload }) };
        let instruction_words = risc0_zkvm::serde::to_vec(&instruction)?;
        let env = ExecutorEnv::builder().write(&OSM_REGISTRY_ID)?
            .write(&Option::<[u32;8]>::None)?.write(&states)?.write(&instruction_words)?.build()?;
        let result = default_executor().execute(env, OSM_REGISTRY_ELF)?;
        measurements.push(serde_json::json!({"operation":name,"entries":count,
            "user_cycles":result.segments.iter().map(|s| s.cycles as u64).sum::<u64>(),
            "total_cycles":result.segments.iter().map(|s| 1u64 << s.po2).sum::<u64>()}));
    }
    println!("{}",serde_json::to_string_pretty(&measurements)?);
    Ok(())
}
