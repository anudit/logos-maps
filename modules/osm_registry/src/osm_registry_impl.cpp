#include "osm_registry_impl.h"
#include <nlohmann/json.hpp>
#include <atomic>
#include <cstdlib>
#include <filesystem>
#include <mutex>
#include <thread>
#include <vector>
#include <cerrno>
#include <cstring>
#include <csignal>
#include <cstdio>
#include <set>
#include <dlfcn.h>
#include <fcntl.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;
using Json = nlohmann::json;
namespace fs = std::filesystem;

namespace {
void locationAnchor() {}
fs::path moduleDirectory() {
    Dl_info info{};
    if (!dladdr(reinterpret_cast<void*>(&locationAnchor), &info) || !info.dli_fname)
        throw std::runtime_error("Cannot locate SDK module assets");
    return fs::absolute(info.dli_fname).parent_path();
}
}

struct OsmRegistryImpl::Worker {
    std::string config;
    pid_t pid = -1;
    int input = -1;
    std::thread reader;
    std::mutex mutex;
    std::vector<Json> events;
    std::set<std::string> outstanding;
    std::atomic<bool> running{false};
    unsigned long nextId = 0;

    ~Worker() { stop(); }
    void stop() {
        if (input >= 0) { close(input); input = -1; }
        if (pid > 0) {
            // EOF lets the worker stop its Storage node cleanly. Bound unload
            // time in case a large operation is blocked on a remote peer.
            bool reaped = false;
            for (int attempt = 0; attempt < 20; ++attempt) {
                if (waitpid(pid, nullptr, WNOHANG) == pid) { reaped = true; break; }
                std::this_thread::sleep_for(std::chrono::milliseconds(100));
            }
            if (!reaped) { kill(pid, SIGTERM); waitpid(pid, nullptr, 0); }
            pid = -1;
        }
        if (reader.joinable()) reader.join();
        running = false;
    }
    void start() {
        if (running) return;
        stop();
        if (config.empty()) throw std::runtime_error("Configure an absolute config JSON path first");
        auto archive = moduleDirectory() / "maps_sdk.pyz";
        const char* overrideArchive = std::getenv("LOGOS_MAPS_ARCHIVE");
        if (overrideArchive) archive = overrideArchive;
        if (!fs::exists(archive)) throw std::runtime_error("SDK Python archive is missing");
        std::string python = "python3";
        if (const char* value = std::getenv("LOGOS_MAPS_PYTHON")) python = value;
        int toChild[2], fromChild[2];
        if (pipe(toChild)) throw std::runtime_error("Cannot create SDK input pipe");
        if (pipe(fromChild)) {
            close(toChild[0]); close(toChild[1]);
            throw std::runtime_error("Cannot create SDK output pipe");
        }
        for (int fd : {toChild[0],toChild[1],fromChild[0],fromChild[1]}) fcntl(fd,F_SETFD,FD_CLOEXEC);
        std::vector<std::string> args = {python, "-u", archive.string(), "--config", config, "worker"};
        std::vector<char*> argv;
        for (auto& arg : args) argv.push_back(arg.data());
        argv.push_back(nullptr);
        posix_spawn_file_actions_t actions;
        posix_spawn_file_actions_init(&actions);
        posix_spawn_file_actions_adddup2(&actions,toChild[0],STDIN_FILENO);
        posix_spawn_file_actions_adddup2(&actions,fromChild[1],STDOUT_FILENO);
        int error = posix_spawnp(&pid, python.c_str(), &actions, nullptr, argv.data(), environ);
        posix_spawn_file_actions_destroy(&actions);
        close(toChild[0]); close(fromChild[1]);
        if (error) {
            close(toChild[1]); close(fromChild[0]); pid = -1;
            throw std::runtime_error(std::string("Cannot start Python SDK: ") + std::strerror(error));
        }
        input = toChild[1];
        running = true;
        reader = std::thread([this, fd=fromChild[0]] {
            FILE* stream = fdopen(fd,"r");
            char* line = nullptr; size_t capacity = 0;
            while (getline(&line,&capacity,stream) >= 0) {
                try {
                    auto event = Json::parse(line);
                    if(!event.contains("id") || (!event.contains("success") && !event.contains("progress"))) continue;
                    std::lock_guard<std::mutex> lock(mutex);
                    // Bound queued progress while preserving final outcomes.
                    if (events.size() > 1000 && event.contains("progress")) continue;
                    if (event.contains("success")) outstanding.erase(event.value("id",std::string()));
                    events.push_back(std::move(event));
                } catch (const Json::exception&) { /* native node log, not a protocol event */ }
            }
            free(line); fclose(stream);
            running = false;
            std::lock_guard<std::mutex> lock(mutex);
            for(const auto& id:outstanding)
                events.push_back({{"id",id},{"success",false},{"error","SDK worker stopped; configure and retry"}});
            outstanding.clear();
        });
    }
    std::string submit(Json job) {
        start();
        job["id"] = std::to_string(++nextId);
        { std::lock_guard<std::mutex> lock(mutex); outstanding.insert(job["id"].get<std::string>()); }
        auto message = job.dump() + "\n";
        size_t offset = 0;
        while (offset < message.size()) {
            // A failed child must produce an error, not terminate logos_host
            // with SIGPIPE. Block the signal only on this calling thread.
            sigset_t blocked, previous;
            sigemptyset(&blocked); sigaddset(&blocked,SIGPIPE);
            pthread_sigmask(SIG_BLOCK,&blocked,&previous);
            ssize_t count = write(input,message.data()+offset,message.size()-offset);
            int writeError = errno;
            if(count < 0 && writeError == EPIPE && !sigismember(&previous,SIGPIPE)) {
                sigset_t pending;
                sigpending(&pending);
                if(sigismember(&pending,SIGPIPE)) { int caught; sigwait(&blocked,&caught); }
            }
            pthread_sigmask(SIG_SETMASK,&previous,nullptr);
            errno = writeError;
            if (count < 0 && errno == EINTR) continue;
            if (count <= 0) throw std::runtime_error("SDK worker input failed");
            offset += static_cast<size_t>(count);
        }
        return Json{{"id",job["id"]}}.dump();
    }
};

OsmRegistryImpl::OsmRegistryImpl() : worker_(std::make_unique<Worker>()) {}
OsmRegistryImpl::~OsmRegistryImpl() = default;

std::string OsmRegistryImpl::configure(const std::string& configPath) {
    try {
        if (!fs::path(configPath).is_absolute() || !fs::is_regular_file(configPath))
            throw std::runtime_error("Choose an existing absolute config JSON path");
        if(worker_->config==configPath) return Json{{"success",true}}.dump();
        { std::lock_guard<std::mutex> lock(worker_->mutex);
          if(!worker_->outstanding.empty()) throw std::runtime_error("Wait for active SDK jobs before changing configuration"); }
        worker_->stop(); worker_->config=configPath;
        return Json{{"success",true}}.dump();
    } catch (const std::exception& e) { return Json{{"success",false},{"error",e.what()}}.dump(); }
}
std::string OsmRegistryImpl::request(const std::string& requestJson) {
    try { return worker_->submit(Json::parse(requestJson)); }
    catch (const std::exception& e) { return Json{{"success",false},{"error",e.what()}}.dump(); }
}
std::string OsmRegistryImpl::poll(const std::string& jobId) {
    std::lock_guard<std::mutex> lock(worker_->mutex);
    Json result=Json::array();
    auto& events=worker_->events;
    auto iterator=events.begin();
    while(iterator!=events.end()) {
        if(iterator->value("id",std::string())==jobId) {
            result.push_back(*iterator); iterator=events.erase(iterator);
        } else ++iterator;
    }
    return result.dump();
}
std::string OsmRegistryImpl::discover(bool central) { return request(Json{{"action","discover"},{"central",central}}.dump()); }
std::string OsmRegistryImpl::resolve(const std::string& region) { return request(Json{{"action","resolve"},{"region",region}}.dump()); }
std::string OsmRegistryImpl::query(const std::string& filtersJson) {
    try { auto job=Json::parse(filtersJson); job["action"]="query"; return request(job.dump()); }
    catch(const std::exception& e) { return Json{{"success",false},{"error",e.what()}}.dump(); }
}
std::string OsmRegistryImpl::host(const std::string& region) { return request(Json{{"action","host"},{"region",region}}.dump()); }
std::string OsmRegistryImpl::bulkHost(const std::string& selectionJson) {
    try { auto job=Json::parse(selectionJson); job["action"]="bulk-host"; return request(job.dump()); }
    catch(const std::exception& e) { return Json{{"success",false},{"error",e.what()}}.dump(); }
}
std::string OsmRegistryImpl::importLocal(const std::string& region,const std::string& file) {
    return request(Json{{"action","import"},{"region",region},{"file",file}}.dump());
}
std::string OsmRegistryImpl::download(const std::string& region,const std::string& destination) {
    return request(Json{{"action","download"},{"region",region},{"destination",destination}}.dump());
}
std::string OsmRegistryImpl::batchRegister(const std::string& entriesJson) {
    try { return request(Json{{"action","batch-register"},{"entries",Json::parse(entriesJson)}}.dump()); }
    catch(const std::exception& e) { return Json{{"success",false},{"error",e.what()}}.dump(); }
}
std::string OsmRegistryImpl::checkUpdates() { return request("{\"action\":\"updates\"}"); }
