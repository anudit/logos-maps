#pragma once
#include <memory>
#include <string>
#include "logos_module_context.h"

/// Basecamp v1 SDK. Operations return a job ID; poll() returns JSON events.
/// A persistent worker serves Storage content until this module is unloaded.
class OsmRegistryImpl : public LogosModuleContext {
public:
    OsmRegistryImpl();
    ~OsmRegistryImpl();
    std::string configure(const std::string& configPath);
    std::string request(const std::string& requestJson);
    std::string poll(const std::string& jobId);
    std::string discover(bool central);
    std::string resolve(const std::string& region);
    std::string query(const std::string& filtersJson);
    std::string host(const std::string& region);
    std::string bulkHost(const std::string& selectionJson);
    std::string importLocal(const std::string& region, const std::string& file);
    std::string download(const std::string& region, const std::string& destination);
    std::string batchRegister(const std::string& entriesJson);
    std::string checkUpdates();
private:
    struct Worker;
    std::unique_ptr<Worker> worker_;
};
