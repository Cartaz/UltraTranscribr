pragma Singleton
import QtQuick
QtObject {
    readonly property color surface: '#141414'
    readonly property color accent: '#ff6600'
    readonly property color primary: '#e1e1e1'
    readonly property color secondary: '#878787'
    readonly property color muted: '#5a5a5a'
    readonly property string font: 'DejaVu Sans'
    readonly property int radiusXL: 28
    readonly property int radiusLG: 22
    readonly property int radiusMD: 16
    readonly property int radiusSM: 12
    function modelName(v) { return {'large-v3':'Large v3','large-v3-turbo':'Large v3 Turbo','medium':'Medium'}[v] || v || '—' }
    function sourceName(v) { return {'system':'Audio di sistema','application':'Applicazione','microphone':'Microfono'}[v] || v || '—' }
    function statusName(v) { return {'idle':'Idle','starting':'Avvio','running':'In esecuzione','completed':'Completata','stopped':'Fermata','error':'Errore','queued':'In coda','recording':'Registrazione','transcribing':'Trascrizione finale','diarizing':'Diarizzazione','finishing':'Chiusura registrazione','cancelled':'Annullata','cancelling':'Annullamento','interrupted':'Interrotta','draining':'Completamento buffer','preparing_backend':'Preparazione backend','isolating_vocals':'Isolamento voce'}[v] || v || 'Idle' }
}
