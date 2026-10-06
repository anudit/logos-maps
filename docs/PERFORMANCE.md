# Guest cycle measurements

`registry/bench` uses the same executor input construction as upstream [LEZ cycle_bench](https://github.com/logos-blockchain/logos-execution-zone/tree/v0.2.4/tools/cycle_bench): program ID, optional caller ID, account pre-states and serialized instruction words. It executes the compiled R0BF guest in `r0vm`; it does not estimate cycles from source lines or time a mocked transition.

```sh
rzup install rust 1.97.0
rzup install cargo-risczero 3.0.5
cargo run --manifest-path registry/bench/Cargo.toml > evidence/cycles.json
```

The benchmark covers `register` with one entry and `batch_register` with 5, 25 and 72 entries against an empty, initialized registry. `user_cycles` sums executed user cycles from every segment; `total_cycles` sums the padded segment lengths (`2^po2`). Measured values are in [cycles.json](../evidence/cycles.json). They apply to this compiled guest, fixture metadata sizes and empty initial history; JSON serialization, validation and retained history affect cost. Re-run after guest/dependency changes and add populated-registry cases for capacity planning. No prover latency or public-testnet gas measurement is claimed.

For upstream baseline measurements, check out LEZ `v0.2.4` and run `cargo run --release -p cycle_bench -- --help`, then its documented executor/prover modes. The upstream tool has a fixed set of built-in programs; the companion benchmark here adds this registry's operations using that same methodology. Local standalone CI uses development proof mode, but the guest still executes and validates its state transition.
