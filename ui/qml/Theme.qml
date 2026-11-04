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
    readonly property var languages: [
        {
            "value": "auto",
            "label": "Rilevamento automatico"
        },
        {
            "value": "it",
            "label": "Italiano"
        },
        {
            "value": "en",
            "label": "Inglese"
        },
        {
            "value": "af",
            "label": "Afrikaans"
        },
        {
            "value": "ar",
            "label": "Arabo"
        },
        {
            "value": "az",
            "label": "Azərbaycan"
        },
        {
            "value": "su",
            "label": "Basa sunda"
        },
        {
            "value": "bs",
            "label": "Bosanski"
        },
        {
            "value": "br",
            "label": "Brezhoneg"
        },
        {
            "value": "ca",
            "label": "Català"
        },
        {
            "value": "sn",
            "label": "Chishona"
        },
        {
            "value": "zh",
            "label": "Cinese"
        },
        {
            "value": "cy",
            "label": "Cymraeg"
        },
        {
            "value": "da",
            "label": "Dansk"
        },
        {
            "value": "et",
            "label": "Eesti"
        },
        {
            "value": "eu",
            "label": "Euskara"
        },
        {
            "value": "tl",
            "label": "Filipino"
        },
        {
            "value": "fr",
            "label": "Francese"
        },
        {
            "value": "fo",
            "label": "Føroyskt"
        },
        {
            "value": "gl",
            "label": "Galego"
        },
        {
            "value": "ja",
            "label": "Giapponese"
        },
        {
            "value": "ha",
            "label": "Hausa"
        },
        {
            "value": "hr",
            "label": "Hrvatski"
        },
        {
            "value": "id",
            "label": "Indonesia"
        },
        {
            "value": "sw",
            "label": "Kiswahili"
        },
        {
            "value": "ht",
            "label": "Kreyòl ayisyen"
        },
        {
            "value": "la",
            "label": "Latina"
        },
        {
            "value": "lv",
            "label": "Latviešu"
        },
        {
            "value": "lt",
            "label": "Lietuvių"
        },
        {
            "value": "ln",
            "label": "Lingála"
        },
        {
            "value": "lb",
            "label": "Lëtzebuergesch"
        },
        {
            "value": "hu",
            "label": "Magyar"
        },
        {
            "value": "mg",
            "label": "Malagasy"
        },
        {
            "value": "mt",
            "label": "Malti"
        },
        {
            "value": "ms",
            "label": "Melayu"
        },
        {
            "value": "mi",
            "label": "Māori"
        },
        {
            "value": "nl",
            "label": "Nederlands"
        },
        {
            "value": "no",
            "label": "Norsk bokmål"
        },
        {
            "value": "nn",
            "label": "Norsk nynorsk"
        },
        {
            "value": "oc",
            "label": "Occitan"
        },
        {
            "value": "uz",
            "label": "O‘zbek"
        },
        {
            "value": "pl",
            "label": "Polski"
        },
        {
            "value": "pt",
            "label": "Portoghese"
        },
        {
            "value": "ro",
            "label": "Română"
        },
        {
            "value": "ru",
            "label": "Russo"
        },
        {
            "value": "sq",
            "label": "Shqip"
        },
        {
            "value": "sk",
            "label": "Slovenčina"
        },
        {
            "value": "sl",
            "label": "Slovenščina"
        },
        {
            "value": "so",
            "label": "Soomaali"
        },
        {
            "value": "es",
            "label": "Spagnolo"
        },
        {
            "value": "fi",
            "label": "Suomi"
        },
        {
            "value": "sv",
            "label": "Svenska"
        },
        {
            "value": "de",
            "label": "Tedesco"
        },
        {
            "value": "vi",
            "label": "Tiếng việt"
        },
        {
            "value": "tk",
            "label": "Türkmen dili"
        },
        {
            "value": "tr",
            "label": "Türkçe"
        },
        {
            "value": "jw",
            "label": "Giavanese"
        },
        {
            "value": "yo",
            "label": "Èdè yorùbá"
        },
        {
            "value": "is",
            "label": "Íslenska"
        },
        {
            "value": "cs",
            "label": "Čeština"
        },
        {
            "value": "haw",
            "label": "ʻōlelo hawaiʻi"
        },
        {
            "value": "el",
            "label": "Ελληνικά"
        },
        {
            "value": "ba",
            "label": "Башҡорт"
        },
        {
            "value": "be",
            "label": "Беларуская"
        },
        {
            "value": "bg",
            "label": "Български"
        },
        {
            "value": "mk",
            "label": "Македонски"
        },
        {
            "value": "mn",
            "label": "Монгол"
        },
        {
            "value": "sr",
            "label": "Српски"
        },
        {
            "value": "tt",
            "label": "Татар"
        },
        {
            "value": "tg",
            "label": "Тоҷикӣ"
        },
        {
            "value": "uk",
            "label": "Українська"
        },
        {
            "value": "kk",
            "label": "Қазақ тілі"
        },
        {
            "value": "hy",
            "label": "Հայերեն"
        },
        {
            "value": "yi",
            "label": "ייִדיש"
        },
        {
            "value": "he",
            "label": "עברית"
        },
        {
            "value": "ur",
            "label": "اردو"
        },
        {
            "value": "sd",
            "label": "سنڌي"
        },
        {
            "value": "fa",
            "label": "فارسی"
        },
        {
            "value": "ps",
            "label": "پښتو"
        },
        {
            "value": "ne",
            "label": "नेपाली"
        },
        {
            "value": "mr",
            "label": "मराठी"
        },
        {
            "value": "sa",
            "label": "संस्कृत भाषा"
        },
        {
            "value": "hi",
            "label": "हिन्दी"
        },
        {
            "value": "as",
            "label": "অসমীয়া"
        },
        {
            "value": "bn",
            "label": "বাংলা"
        },
        {
            "value": "pa",
            "label": "ਪੰਜਾਬੀ"
        },
        {
            "value": "gu",
            "label": "ગુજરાતી"
        },
        {
            "value": "ta",
            "label": "தமிழ்"
        },
        {
            "value": "te",
            "label": "తెలుగు"
        },
        {
            "value": "kn",
            "label": "ಕನ್ನಡ"
        },
        {
            "value": "ml",
            "label": "മലയാളം"
        },
        {
            "value": "si",
            "label": "සිංහල"
        },
        {
            "value": "th",
            "label": "ไทย"
        },
        {
            "value": "lo",
            "label": "ລາວ"
        },
        {
            "value": "bo",
            "label": "བོད་སྐད་"
        },
        {
            "value": "my",
            "label": "မြန်မာ"
        },
        {
            "value": "ka",
            "label": "ქართული"
        },
        {
            "value": "am",
            "label": "አማርኛ"
        },
        {
            "value": "km",
            "label": "ខ្មែរ"
        },
        {
            "value": "yue",
            "label": "粵語"
        },
        {
            "value": "ko",
            "label": "한국어"
        }
    ]
    readonly property var meetingLanguages: languages.filter(row => ['en', 'it', 'fr', 'de', 'es', 'pt', 'ru', 'ja', 'ko', 'zh'].indexOf(row.value) >= 0)
    function languageName(code) {
        for (let row of languages)
            if (row.value === code)
                return row.label;
        return code || "Rilevamento automatico";
    }
    function timestamp(seconds) {
        let s = Math.floor(Math.max(0, seconds));
        return String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
    }
    function modelName(v) {
        return {
            'large-v3': 'Large v3',
            'large-v3-turbo': 'Large v3 Turbo',
            'medium': 'Medium'
        }[v] || v || '—';
    }
    function sourceName(v) {
        return {
            'system': 'Audio di sistema',
            'application': 'Applicazione',
            'microphone': 'Microfono'
        }[v] || v || '—';
    }
    function statusName(v) {
        return {
            'idle': 'Idle',
            'starting': 'Avvio',
            'running': 'In esecuzione',
            'completed': 'Completata',
            'stopped': 'Fermata',
            'error': 'Errore',
            'queued': 'In coda',
            'recording': 'Registrazione',
            'transcribing': 'Trascrizione finale',
            'diarizing': 'Diarizzazione',
            'finishing': 'Chiusura registrazione',
            'cancelled': 'Annullata',
            'cancelling': 'Annullamento',
            'interrupted': 'Interrotta',
            'draining': 'Completamento buffer',
            'preparing_backend': 'Preparazione backend',
            'isolating_vocals': 'Isolamento voce'
        }[v] || v || 'Idle';
    }
}
