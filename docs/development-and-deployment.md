# Entwicklung und Deployment

Code und die beiden produktiven Modelle werden gemeinsam versioniert. Die Modelle liegen über Git LFS unter `club_model_v3.joblib` und `model.joblib`; `model-manifest.json` hält ihre Prüfsummen und Herkunft fest.

## Lokal

Git LFS installieren (macOS: `brew install git-lfs`), dann `git lfs install --local` und `git lfs pull`. `./setup.sh` verwendet den aktuellen Projektordner und eine eigene `.venv`. Python 3.11 oder neuer verwenden. Backend: `./start_api.sh`; Frontend: `cd frontend && npm run dev`.

## Prüfen und veröffentlichen

GitHub Actions lädt beim Checkout die echten LFS-Dateien. Der Workflow „Verify deployable image“ baut auf PRs und Änderungen an main das vollständige Docker-Image. Dabei prüft `scripts/verify_models.py` beide Dateien gegen das Manifest, lädt beide Modelle und berechnet Testvorhersagen. Fehlende Dateien, LFS-Platzhalter, falsche Prüfsummen oder fehlgeschlagene Vorhersagen stoppen den Build.

„Deploy to Fly“ bleibt manuell. Auch dieser Workflow lädt LFS und durchläuft dieselbe Prüfung im Docker-Build, bevor eine laufende Maschine ersetzt wird. Keine lokalen, unversionierten Modelle beifügen. Zugangsdaten sind vom Docker-Kontext ausgeschlossen.

## Modelle aktualisieren

Nur gezielt trainierte und geprüfte Artefakte ersetzen. Dann die Größen und SHA-256-Werte im Manifest aktualisieren und Modelle sowie Manifest gemeinsam committen. Modellbibliotheken sind in requirements.txt festgelegt und gelten lokal sowie auf Fly. Ein erfolgreicher Smoke-Test prüft die technische Funktionsfähigkeit, nicht die statistische Modellqualität.
