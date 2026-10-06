{
  inputs = {
    logos-module-builder.url = "github:logos-co/logos-module-builder/3a64943fe6827bab4c4686fb35c37d24d5df0710";
    storage_module.url = "github:logos-co/logos-storage-module/7548f41ae189917d58c37f0fb6d3a2700b99f59b";
  };
  outputs = inputs@{ logos-module-builder, ... }:
    let
      base = logos-module-builder.lib.mkLogosModule {
      src = ./.;
      configFile = ./metadata.json;
      flakeInputs = inputs;
        postInstall = ''
          mkdir -p $out/share/maps-engine
          cp ${./maps_sdk.pyz} ${./idl.json} $out/share/maps-engine/
        '';
      };
      withEngine = drv: drv // {
        lgxAssets = (drv.lgxAssets or {}) // { engine = "share/maps-engine"; };
      };
      bundlers = logos-module-builder.inputs.nix-bundle-lgx.bundlers;
    in base // {
      packages = builtins.mapAttrs (system: packages: packages // {
        lib = withEngine packages.lib;
        lib-portable = withEngine packages.lib-portable;
        lgx = bundlers.${system}.default (withEngine packages.lib);
        lgx-portable = bundlers.${system}.portable (withEngine packages.lib-portable);
      }) base.packages;
    };
}
