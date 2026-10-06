fn main() {
    println!("cargo:rerun-if-changed=../src");
    println!("cargo:rerun-if-changed=../Cargo.toml");
    println!("cargo:rerun-if-changed=../guest/src");
    println!("cargo:rerun-if-changed=../guest/Cargo.toml");
    risc0_build::embed_methods();
}
