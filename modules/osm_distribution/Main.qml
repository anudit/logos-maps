import QtQuick 2.15
import QtQuick.Controls.Basic
import QtQuick.Layouts 1.15

Pane {
    id: app
    width: 1080; height: 760
    padding: 0
    background: Rectangle { color: "#111916" }
    palette.window: "#111916"
    palette.windowText: "#eff4ed"
    palette.base: "#1a2520"
    palette.text: "#eff4ed"
    palette.button: "#2b4033"
    palette.buttonText: "#eff4ed"
    palette.highlight: "#a8c9b4"
    palette.highlightedText: "#111916"
    palette.placeholderText: "#a4b0a9"
    property var regions: []
    property var selected: ({})
    property var pending: ({})
    property bool configured: false
    property string status: "Choose a configuration file to connect to your registry."
    property bool failed: false
    property bool busy: Object.keys(pending).length > 0
    property int selectedCount: Object.keys(selected).length
    property int hostedCount: regions.filter(function(r) { return r.hosted }).length
    Component.onCompleted: {
        if (typeof previewConfigPath !== "undefined") {
            config.text = previewConfigPath
            connectConfig()
        }
    }

    function decode(value) {
        for (var i = 0; i < 3 && typeof value === "string"; i++) {
            try { value = JSON.parse(value) } catch (e) { break }
        }
        return value
    }
    function call(method, args) {
        var value = decode(logos.callModule("osm_registry", method, args))
        if (value && value.error) throw new Error(value.error)
        return value
    }
    function submit(request) {
        try {
            var result = call("request", [JSON.stringify(request)])
            if (!result || !result.id) throw new Error("SDK did not return a job ID")
            var jobs = Object.assign({}, pending)
            jobs[result.id] = request.action
            pending = jobs
            failed = false
            status = "Working: " + request.action + ". Keep this app open to mirror hosted files."
        } catch (e) { failed = true; status = e.message }
    }
    function selection(region, checked) {
        var next = Object.assign({}, selected)
        if (checked) next[region] = true
        else delete next[region]
        selected = next
    }
    function oneSelected() { return Object.keys(selected)[0] }
    function refresh() { submit({action:"discover", central:false}) }
    function connectConfig() {
        try {
            var value = app.call("configure", [config.text])
            if (!value.success) throw new Error("Configuration failed")
            app.configured = true
            app.submit({action:"regions"})
            app.refresh()
        } catch(e) { app.failed=true; app.status=e.message }
    }

    Timer {
        interval: 300; repeat: true; running: app.configured
        onTriggered: {
            try {
                var events = []
                Object.keys(app.pending).forEach(function(id) { events = events.concat(app.call("poll", [id])) })
                for (var i = 0; i < events.length; i++) {
                    var event = events[i]
                    if (event.progress) {
                        var progress = event.progress
                        if (progress.phase === "fetch") app.status = "Downloading from Geofabrik: " + Math.round(progress.bytes / 1048576) + " MiB"
                        else if (progress.phase === "verified") app.status = "Checksum verified: " + progress.region + ". Uploading to Logos Storage…"
                        else if (progress.phase === "retry") app.status = "Storage retry " + progress.attempt + " in " + progress.delay + " seconds"
                        continue
                    }
                    var action = app.pending[event.id]
                    if (!action) continue
                    var jobs = Object.assign({}, app.pending)
                    delete jobs[event.id]; app.pending = jobs
                    if (!event.success) { app.failed = true; app.status = event.error; continue }
                    if (action === "regions" || action === "discover") {
                        app.regions = event.result
                        app.status = "72 predefined regions · " + event.result.filter(function(r) {return r.hosted}).length + " hosted"
                    } else if (action === "updates") {
                        app.status = event.result.length + " regions have a newer or unhosted snapshot."
                        details.text = JSON.stringify(event.result, null, 2)
                    } else {
                        app.status = "Completed " + action + (event.result.verified ? " · integrity verified" : "")
                        details.text = JSON.stringify(event.result, null, 2)
                        if (action === "host" || action === "bulk-host" || action === "import") app.refresh()
                    }
                }
            } catch (e) { app.failed = true; app.status = e.message }
        }
    }

    ColumnLayout {
        anchors.fill: parent; anchors.margins: 28; spacing: 18
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                spacing: 3
                Label { text: "LOGOS / MAPS"; color: "#a8c9b4"; font.pixelSize: 12; font.letterSpacing: 3 }
                Label { text: "Share the world, one region at a time."; color: "#eff4ed"; font.pixelSize: 26; font.bold: true }
                Label { text: "Verified OSM snapshots · 72 regions · no overlapping extracts"; color: "#a4b0a9" }
            }
            Item { Layout.fillWidth: true }
            BusyIndicator { running: app.busy; visible: running; Layout.preferredWidth: 36; Layout.preferredHeight: 36 }
        }
        RowLayout {
            Layout.fillWidth: true
            TextField { id: config; Layout.fillWidth: true; placeholderText: "Absolute path to config.local.json"; Accessible.name: "Configuration path" }
            Button {
                text: "Connect"; enabled: !app.busy
                onClicked: app.connectConfig()
            }
        }
        RowLayout {
            TextField { id: search; Layout.fillWidth: true; placeholderText: "Find a country or subregion…"; Accessible.name: "Search regions" }
            Button { text: "Registry"; enabled: app.configured && !app.busy; onClicked: app.refresh() }
            Button { text: "Geofabrik versions"; enabled: app.configured && !app.busy; onClicked: app.submit({action:"discover",central:true}) }
            Button { text: "Check updates"; enabled: app.configured && !app.busy; onClicked: app.submit({action:"updates"}) }
        }
        RowLayout {
            Label { text: app.selectedCount + " selected"; color: "#b9d5c2" }
            Button { text: "Select visible"; enabled: !app.busy; onClicked: {
                var next = Object.assign({}, app.selected)
                app.regions.forEach(function(r) { if ((r.name + " " + r.region).toLowerCase().indexOf(search.text.toLowerCase()) >= 0) next[r.region] = true })
                app.selected = next
            } }
            Button { text: "Clear selection"; enabled: !app.busy; onClicked: app.selected = ({}) }
            Item { Layout.fillWidth: true }
            Button { text: "Host selected"; enabled: app.configured && app.selectedCount > 0 && !app.busy; onClicked: app.submit({action:"bulk-host",regions:Object.keys(app.selected)}) }
        }
        Rectangle {
            Layout.fillWidth: true; Layout.fillHeight: true; color: "#1a2520"; border.color: "#34473c"; radius: 8
            ListView {
                id: list; anchors.fill: parent; anchors.margins: 8; clip: true; spacing: 1; model: app.regions
                ScrollBar.vertical: ScrollBar {}
                delegate: Rectangle {
                    required property var modelData
                    width: list.width
                    property bool matches: (modelData.name + " " + modelData.region).toLowerCase().indexOf(search.text.toLowerCase()) >= 0
                    height: matches ? 65 : 0; visible: matches
                    color: app.selected[modelData.region] ? "#2b4033" : "transparent"
                    RowLayout {
                        anchors.fill: parent; anchors.margins: 8; spacing: 12
                        CheckBox {
                            checked: !!app.selected[modelData.region]; enabled: !app.busy
                            Accessible.name: "Select " + modelData.name
                            onClicked: app.selection(modelData.region, checked)
                        }
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 3
                            Label { text: modelData.name; color: "#edf1eb"; font.pixelSize: 15 }
                            Label { text: modelData.region + " · " + modelData.level + (modelData.parent ? " · parent: " + modelData.parent : ""); color: "#acb7af"; font.pixelSize: 11 }
                        }
                        ColumnLayout {
                            Layout.preferredWidth: 220; spacing: 3
                            Label { text: modelData.registered ? "Hosted: " + modelData.registered.version.slice(0,10) : (modelData.hosted === undefined ? "Registry not loaded" : "Not hosted"); color: modelData.hosted ? "#b8df96" : "#a4b0a9" }
                            Label { text: modelData.central ? "Geofabrik: " + modelData.central.version.slice(0,10) : (modelData.available === false ? "Geofabrik: unavailable" : ""); color: "#a4b0a9"; font.pixelSize: 11 }
                        }
                        Button { text: "Details"; onClicked: details.text = JSON.stringify(modelData,null,2) }
                    }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            TextField { id: destination; Layout.fillWidth: true; placeholderText: "Absolute destination file or local PBF to import"; Accessible.name: "File path" }
            Button { text: "Download"; enabled: app.selectedCount === 1 && app.configured && !app.busy && destination.text.length > 0; onClicked: app.submit({action:"download",region:app.oneSelected(),destination:destination.text}) }
            Button { text: "Verify & import"; enabled: app.selectedCount === 1 && app.configured && !app.busy && destination.text.length > 0; onClicked: app.submit({action:"import",region:app.oneSelected(),file:destination.text}) }
        }
        Label { Layout.fillWidth: true; text: app.status; color: app.failed ? "#f8ab98" : "#bed6c7"; wrapMode: Text.Wrap; Accessible.name: "Workflow status" }
        ScrollView {
            Layout.fillWidth: true; Layout.preferredHeight: 100
            TextArea {
                id: details; readOnly: true; color: "#eff4ed"
                background: Rectangle { color: "#1a2520"; border.color: "#34473c" }
                text: "Select Details to inspect CID, version, parent and verification metadata."
                font.family: "monospace"; font.pixelSize: 11; wrapMode: TextEdit.Wrap
            }
        }
        Label { text: "OpenStreetMap contributors · ODbL data · Geofabrik extracts. Keep the SDK loaded to serve hosted files."; color: "#8c9b91"; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true }
    }
}
