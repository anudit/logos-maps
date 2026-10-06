import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
ColumnLayout {
    width: 640; height: 400
    property string jobId: ""
    function call(method,args) {
        var value=logos.callModule("osm_registry",method,args)
        for(var i=0;i<3 && typeof value==="string";i++) value=JSON.parse(value)
        return value
    }
    Label { text: "Standalone OSM registry consumer"; font.pixelSize: 22 }
    TextField { id: config; placeholderText: "Absolute config JSON path"; Layout.fillWidth: true }
    TextField { id: region; text: "germany"; Accessible.name: "Region" }
    Button {
        text: "Resolve to CID and metadata"; enabled: jobId === ""
        onClicked: {
            try {
                var configured=call("configure",[config.text])
                if (!configured.success) throw new Error(configured.error)
                var job=call("resolve",[region.text])
                if(!job.id) throw new Error(job.error)
                jobId=job.id
            } catch(e) { output.text=e.message }
        }
    }
    Timer {
        interval: 300; repeat: true; running: jobId !== ""
        onTriggered: {
            var events=call("poll",[jobId])
            for(var i=0;i<events.length;i++) if(events[i].id === jobId && !events[i].progress) {
                output.text=JSON.stringify(events[i],null,2); jobId=""
            }
        }
    }
    ScrollView { Layout.fillWidth: true; Layout.fillHeight: true
        TextArea { id: output; readOnly: true; wrapMode: TextEdit.Wrap; text: "Uses only osm_registry. No distribution UI dependency." }
    }
}
