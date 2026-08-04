# LICENSE — korrekt MIT-attribution (original + din utökning)
cat > ~/ha-reolink-talk/LICENSE << 'EOF'
MIT License

Copyright (c) 2026 joeblack2k (original project)
Copyright (c) 2026 Mathias Holm (this fork/extension)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
EOF

# hacs.json — samma mönster som originalet, så HACS hittar och listar den korrekt
cat > ~/ha-reolink-talk/hacs.json << 'EOF'
{
  "name": "Reolink Talk (Two-Way Audio + Live Talk)",
  "content_in_root": false,
  "render_readme": true,
  "zip_release": true
}
EOF

# info.md — kort text HACS visar i store-vyn
cat > ~/ha-reolink-talk/info.md << 'EOF'
# Reolink Talk (Two-Way Audio + Live Talk)

Two-way audio for Reolink cameras behind a Home Hub/NVR, straight from Home Assistant.

- One-shot TTS/file playback via a `media_player` entity
- Live push-to-talk with an inline Lovelace button, no separate server or extra video stream

Fork of [joeblack2k/reolink_talk](https://github.com/joeblack2k/reolink_talk), MIT licensed.
EOF

# Peka om manifest.json till ditt eget repo
python3 - << 'PYEOF'
import json
from pathlib import Path

p = Path.home() / "ha-reolink-talk/custom_components/reolink_talk/manifest.json"
data = json.loads(p.read_text())
data["documentation"] = "https://github.com/mathiasmholm/ha-reolink-talk"
data["issue_tracker"] = "https://github.com/mathiasmholm/ha-reolink-talk/issues"
data["version"] = "0.2.0"
p.write_text(json.dumps(data, indent=2) + "\n")
print(p.read_text())
PYEOF

# Lägg README.md på plats (kopiera in innehållet du fick från mig i outputs-mappen)
