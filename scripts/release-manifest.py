"""Проверить фактическую ревизию моделей клиента и записать контрольные суммы релиза."""
from pathlib import Path
import hashlib
import json
import os
import struct

root=Path(__file__).resolve().parents[1]
installer=root/'artifacts/Агроэкосистема_1.0.0_x64-setup.exe'
client=root/'AgroecosystemTauri/src-tauri/target/release/agroecosystemtauri.exe'
sidecar=root/'AgroecosystemTauri/src-tauri/target/release/python_service.exe'
names=['BOD','COD','Ammonium','Phosphates','Nitrates','Nitrites','Fats','Sulfates']
models=[root/'models'/f'module1_model_{name}.pkl' for name in names]
models += [root/'python_service/data/models'/name for name in ['module2_dosing_config.pkl','module3_sediments.pkl']]
digest=hashlib.sha256()
for model in models:
    digest.update(model.name.encode())
    digest.update(model.read_bytes())
revision=digest.hexdigest()
marker=Path(os.environ['APPDATA'])/'com.agroecosystem.agroecosystem/wtp-data/.bundled-models.sha256'
assert marker.read_text()==revision, 'Native client model revision does not match the ML delivery'
for binary in [client,sidecar]:
    with binary.open('rb') as stream:
        stream.seek(0x3c)
        pe=struct.unpack('<I',stream.read(4))[0]
        stream.seek(pe+4)
        assert struct.unpack('<H',stream.read(2))[0]==0x8664, f'Not Windows x64: {binary}'
artifacts={}
for file in [installer,client,sidecar]:
    with file.open('rb') as stream:
        sha=hashlib.file_digest(stream,'sha256').hexdigest()
    artifacts[file.name]={'bytes':file.stat().st_size,'sha256':sha}
manifest={'version':'1.0.0','platform':'windows-x64','model_revision':revision,'model_artifacts':len(models),
          'water_models':8,'sediment_models':14,'required_fields':49,'artifacts':artifacts,
          'checks':['source and frozen sidecar forecasts','49-field validation and save','JSON import and draft restoration',
                    'CSV UTF-8 BOM export','native model migration','native frontend IPC startup','single instance']}
(root/'artifacts/release-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Windows x64 payloads and native model revision: OK')
print('Installer SHA256:',artifacts[installer.name]['sha256'])
