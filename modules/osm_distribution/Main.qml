import QtQuick 2.15
import QtQuick.Controls.Basic
import QtQuick.Layouts 1.15
import QtQuick.Dialogs
import QtCore

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
    readonly property bool compact: width < 850
    component ActionButton: Button {
        implicitHeight: 36
        leftPadding: 14; rightPadding: 14
        font.pixelSize: 13
        opacity: enabled ? 1 : 0.4
        background: Rectangle {
            radius: 4
            color: parent.down ? "#3b5544" : parent.hovered ? "#344b3c" : "#2b4033"
            border.color: parent.activeFocus ? "#a8c9b4" : "transparent"
        }
    }
    component InputField: TextField {
        implicitHeight: 36
        leftPadding: 12; rightPadding: 12
        font.pixelSize: 13
        background: Rectangle {
            radius: 4; color: "#1a2520"
            border.color: parent.activeFocus ? "#a8c9b4" : "#526358"
        }
    }
    property var inspectedRegion: null
    property bool detailsOpen: false
    property bool rawDetails: false
    property string detailText: ""
    function inspect(region) {
        inspectedRegion = region
        detailText = JSON.stringify(region, null, 2)
        detailsOpen = true
        rawDetails = false
    }
    function detailSummary() {
        if (!inspectedRegion) return "Operation result"
        var region = inspectedRegion
        var entry = region.registered || region
        var parts = [region.name || region.region || "Snapshot"]
        if (entry.version) parts.push("Version " + entry.version.slice(0,10))
        if (region.parent) parts.push("Parent: " + region.parent)
        if (entry.size !== undefined) parts.push(entry.size.toLocaleString() + " bytes")
        return parts.join(" · ")
    }
    property var regions: []
    property var selected: ({})
    property var pending: ({})
    property bool configured: false
    property bool settingsOpen: false
    property bool centralEnabled: true
    property string connectionLabel: "No registry connected"
    property string status: "Connecting to your saved registry…"
    property bool failed: false
    property bool busy: Object.keys(pending).length > 0
    property int selectedCount: Object.keys(selected).length
    property int hostedCount: regions.filter(function(r) { return r.hosted }).length
    Component.onCompleted: {
        if (typeof previewConfigPath !== "undefined") {
            config.text = previewConfigPath
        }
        connectConfig(true)
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
    function localPath(url) {
        var text = String(url)
        if (text.indexOf("file://") !== 0) throw new Error("Choose a local file")
        return decodeURIComponent(text.slice(7))
    }
    function connectConfig(automatic) {
        try {
            var value = app.call("configure", [config.text])
            if (value && value.needs_configuration) {
                app.settingsOpen = true
                app.status = "Choose your registry configuration once. This connection will be remembered."
                return
            }
            if (!value.success) throw new Error("Configuration failed")
            config.text = value.config_path || config.text
            app.connectionLabel = value.label || "OSM registry"
            app.centralEnabled = value.central_enabled !== false
            app.configured = true
            app.settingsOpen = false
            app.submit({action:"regions"})
            app.refresh()
        } catch(e) {
            if (!automatic) { app.failed=true; app.status=e.message }
            else app.status = "Waiting for the registry SDK…"
        }
    }
    Timer {
        property int attempts: 0
        interval: 1000; repeat: true
        running: !app.configured && !app.settingsOpen && attempts < 5
        onTriggered: {
            attempts++
            app.connectConfig(true)
            if (!app.configured && attempts === 5) {
                app.settingsOpen = true
                app.status = "Choose a registry connection to get started."
            }
        }
    }
    FileDialog {
        id: configDialog
        title: "Choose registry configuration"
        fileMode: FileDialog.OpenFile
        nameFilters: ["Registry configuration (*.json)"]
        onAccepted: { config.text = app.localPath(selectedFile); app.connectConfig(false) }
    }
    FileDialog {
        id: downloadDialog
        title: "Save " + app.oneSelected() + " map"
        fileMode: FileDialog.SaveFile
        defaultSuffix: "osm.pbf"
        nameFilters: ["OpenStreetMap extract (*.osm.pbf)"]
        onAccepted: app.submit({action:"download",region:app.oneSelected(),destination:app.localPath(selectedFile)})
    }
    FileDialog {
        id: importDialog
        title: "Import map for " + app.oneSelected()
        fileMode: FileDialog.OpenFile
        nameFilters: ["OpenStreetMap extract (*.osm.pbf)"]
        onAccepted: app.submit({action:"import",region:app.oneSelected(),file:app.localPath(selectedFile)})
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
                        app.inspectedRegion = null; app.detailText = JSON.stringify(event.result, null, 2); app.detailsOpen = true; app.rawDetails = true
                    } else {
                        app.status = "Completed " + action + (event.result.verified ? " · integrity verified" : "")
                        app.inspectedRegion = null; app.detailText = JSON.stringify(event.result, null, 2); app.detailsOpen = true; app.rawDetails = true
                        if (action === "host" || action === "bulk-host" || action === "import") app.refresh()
                    }
                }
            } catch (e) { app.failed = true; app.status = e.message }
        }
    }

    ColumnLayout {
        anchors.fill: parent; anchors.margins: app.compact ? 20 : 24; spacing: 12
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                Layout.fillWidth: true; spacing: 6
                Label { text: "LOGOS / MAPS"; color: "#a8c9b4"; font.pixelSize: 12; font.letterSpacing: 3 }
                Label { Layout.fillWidth: true; text: "Share the world, one region at a time."; color: "#eff4ed"; font.pixelSize: app.compact ? 22 : 26; font.bold: true; wrapMode: Text.Wrap }
                Label { text: "Verified OSM snapshots · 72 regions"; color: "#a4b0a9" }
            }
            BusyIndicator { running: app.busy; visible: running; Layout.preferredWidth: 36; Layout.preferredHeight: 36 }
        }
        RowLayout {
            Layout.fillWidth: true
            Label { text: (app.configured ? "●  " : "○  ") + app.connectionLabel; color: "#bed6c7" }
            Item { Layout.fillWidth: true }
            ActionButton { text: "Connection settings"; enabled: !app.busy; onClicked: app.settingsOpen = !app.settingsOpen }
        }
        GridLayout {
            columns: app.compact ? 2 : 3
            columnSpacing: 8; rowSpacing: 8
            visible: app.settingsOpen
            Layout.fillWidth: true
            InputField { id: config; Layout.columnSpan: app.compact ? 2 : 1; Layout.fillWidth: true; placeholderText: "Registry configuration (advanced)"; Accessible.name: "Configuration path" }
            ActionButton { text: "Choose file…"; enabled: !app.busy; onClicked: configDialog.open() }
            ActionButton {
                text: "Connect"; enabled: !app.busy
                onClicked: app.connectConfig(false)
            }
        }
        GridLayout {
            Layout.fillWidth: true
            columns: app.compact ? 3 : 4
            columnSpacing: 8; rowSpacing: 8
            InputField { id: search; Layout.row: 0; Layout.column: 0; Layout.columnSpan: app.compact ? 3 : 1; Layout.fillWidth: true; placeholderText: "Find a country or subregion…"; Accessible.name: "Search regions" }
            ActionButton { Layout.row: app.compact ? 1 : 0; Layout.column: app.compact ? 0 : 1; Layout.fillWidth: app.compact; text: "Registry"; enabled: app.configured && !app.busy; onClicked: app.refresh() }
            ActionButton { Layout.row: app.compact ? 1 : 0; Layout.column: app.compact ? 1 : 2; Layout.fillWidth: app.compact; text: "Geofabrik versions"; enabled: app.configured && app.centralEnabled && !app.busy; onClicked: app.submit({action:"discover",central:true}) }
            ActionButton { Layout.row: app.compact ? 1 : 0; Layout.column: app.compact ? 2 : 3; Layout.fillWidth: app.compact; text: "Check updates"; enabled: app.configured && app.centralEnabled && !app.busy; onClicked: app.submit({action:"updates"}) }
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 8
            Label { Layout.preferredWidth: 88; text: app.selectedCount + " selected"; color: "#b9d5c2" }
            ActionButton { text: "Select visible"; enabled: !app.busy; onClicked: {
                var next = Object.assign({}, app.selected)
                app.regions.forEach(function(r) { if ((r.name + " " + r.region).toLowerCase().indexOf(search.text.toLowerCase()) >= 0) next[r.region] = true })
                app.selected = next
            } }
            ActionButton { text: "Clear selection"; enabled: !app.busy; onClicked: app.selected = ({}) }
            Item { Layout.fillWidth: true }
            ActionButton { text: "Host selected"; enabled: app.configured && app.centralEnabled && app.selectedCount > 0 && !app.busy; onClicked: app.submit({action:"bulk-host",regions:Object.keys(app.selected)}) }
        }
        Rectangle {
            Layout.fillWidth: true; Layout.fillHeight: true; color: "#1a2520"; border.color: "#34473c"; radius: 8
            ListView {
                id: list; anchors.fill: parent; anchors.margins: 8; clip: true; spacing: 0; model: app.regions
                ScrollBar.vertical: ScrollBar {}
                delegate: Rectangle {
                    required property var modelData
                    width: list.width
                    property bool matches: (modelData.name + " " + modelData.region).toLowerCase().indexOf(search.text.toLowerCase()) >= 0
                    height: matches ? 64 : 0; visible: matches
                    color: app.selected[modelData.region] ? "#2b4033" : "transparent"
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 16; spacing: 12
                        CheckBox {
                            Layout.preferredWidth: 28; Layout.preferredHeight: 32
                            padding: 0
                            indicator: Rectangle {
                                implicitWidth: 20; implicitHeight: 20
                                x: 0; y: (parent.height - height) / 2
                                radius: 3; color: parent.checked ? "#a8c9b4" : "transparent"
                                border.color: parent.activeFocus ? "#eff4ed" : "#75897d"
                                Label { anchors.centerIn: parent; text: "✓"; visible: parent.parent.checked; color: "#111916"; font.pixelSize: 15 }
                            }
                            checked: !!app.selected[modelData.region]; enabled: !app.busy
                            Accessible.name: "Select " + modelData.name
                            onClicked: app.selection(modelData.region, checked)
                        }
                        ColumnLayout {
                            Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 3
                            Label { Layout.fillWidth: true; elide: Text.ElideRight; text: modelData.name; color: "#edf1eb"; font.pixelSize: 15 }
                            Label { Layout.fillWidth: true; elide: Text.ElideRight; text: modelData.region + " · " + modelData.level + (modelData.parent ? " · parent: " + modelData.parent : ""); color: "#acb7af"; font.pixelSize: 11 }
                        }
                        ColumnLayout {
                            Layout.minimumWidth: app.compact ? 150 : 200
                            Layout.maximumWidth: Layout.minimumWidth
                            Layout.preferredWidth: Layout.minimumWidth; spacing: 3
                            Label { Layout.fillWidth: true; elide: Text.ElideRight; font.pixelSize: 12; text: modelData.registered ? "Hosted: " + modelData.registered.version.slice(0,10) : (modelData.hosted === undefined ? "Registry not loaded" : "Not hosted"); color: modelData.hosted ? "#b8df96" : "#a4b0a9" }
                            Label { text: modelData.central ? "Geofabrik: " + modelData.central.version.slice(0,10) : (modelData.available === false ? "Geofabrik: unavailable" : ""); color: "#a4b0a9"; font.pixelSize: 11 }
                        }
                        ActionButton { Layout.preferredWidth: 80; text: "Details"; onClicked: app.inspect(modelData) }
                    }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 8
            Label { Layout.fillWidth: true; wrapMode: Text.Wrap; font.pixelSize: 12; text: app.selectedCount === 1 ? "Ready: " + app.oneSelected() : "Select one region to download or import a map."; color: "#a4b0a9" }
            ActionButton {
                text: "Download…"; enabled: app.selectedCount === 1 && app.configured && !app.busy
                onClicked: {
                    var folder = StandardPaths.writableLocation(StandardPaths.DownloadLocation)
                    downloadDialog.currentFolder = "file://" + folder
                    downloadDialog.currentFile = "file://" + folder + "/" + app.oneSelected().replace(/\//g,"-") + ".osm.pbf"
                    downloadDialog.open()
                }
            }
            ActionButton { text: "Import PBF…"; enabled: app.selectedCount === 1 && app.configured && app.centralEnabled && !app.busy; onClicked: importDialog.open() }
        }
        Label { Layout.fillWidth: true; text: app.status; color: app.failed ? "#f8ab98" : "#bed6c7"; wrapMode: Text.Wrap; Accessible.name: "Workflow status" }
        ColumnLayout {
            visible: app.detailsOpen
            Layout.fillWidth: true
            spacing: 6
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                Label { Layout.fillWidth: true; text: app.detailSummary(); color: "#eff4ed"; font.pixelSize: 12; elide: Text.ElideRight }
                ActionButton { text: app.rawDetails ? "Summary" : "Metadata"; onClicked: app.rawDetails = !app.rawDetails }
                ActionButton { text: "Close"; onClicked: app.detailsOpen = false }
            }
            ScrollView {
                Layout.fillWidth: true
                Layout.preferredHeight: app.rawDetails ? 100 : 54
                TextArea {
                    readOnly: true; color: "#bed6c7"
                    text: app.rawDetails ? app.detailText : (app.inspectedRegion && app.inspectedRegion.registered ? "CID: " + app.inspectedRegion.registered.cid + "\nSHA-256: " + app.inspectedRegion.registered.sha256 : "This region has no registered snapshot.")
                    background: Rectangle { radius: 4; color: "#1a2520"; border.color: "#34473c" }
                    leftPadding: 12; rightPadding: 12; topPadding: 8; bottomPadding: 8
                    font.family: Qt.platform.os === "osx" ? "Menlo" : "monospace"; font.pixelSize: 11; wrapMode: TextEdit.Wrap
                }
            }
        }
        Label { text: "OpenStreetMap contributors · ODbL data · Geofabrik extracts. Keep the SDK loaded to serve hosted files."; color: "#8c9b91"; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true }
    }
}
