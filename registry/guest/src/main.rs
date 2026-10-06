#![no_main]
risc0_zkvm::guest::entry!(main);
fn main() { osm_registry::main(); }
