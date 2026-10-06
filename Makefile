.PHONY: test idl registry modules
test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v
	cargo test --manifest-path registry/Cargo.toml
idl:
	cargo run --manifest-path registry/Cargo.toml --bin generate-idl > registry/idl.json.tmp
	mv registry/idl.json.tmp registry/idl.json
registry:
	cargo build --manifest-path registry/methods/Cargo.toml
modules:
	nix build path:./modules/osm_registry\#lgx
	nix build path:./modules/osm_distribution\#lgx
