fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Use SPEL's compiled program schema; it includes owner constraints which
    // the pinned framework's file-parser generator currently omits.
    let idl = osm_registry::__program_idl();
    println!("{}", serde_json::to_string_pretty(&idl)?);
    Ok(())
}
