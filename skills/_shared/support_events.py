"""Allowlisted support events and offline bundle, with no source-log ingestion or sending.

Source of truth: report-kit-skills/skills/_shared. The identical module and policy
are shipped in agent/scripts for a fallback that does not need a running agent.
"""
import argparse
import importlib.metadata
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import uuid
import zipfile

POLICY = json.loads(Path(__file__).with_name('support-policy.json').read_text(encoding='utf-8'))
PACKAGE = Path(__file__).resolve().parents[2 if Path(__file__).parent.name == '_shared' else 1]
RUN = str(uuid.uuid4())
SEQUENCE = 0
WARNED = False
VERSION = re.compile(r'\d{1,6}\.\d{1,6}(?:\.\d{1,6}){0,2}(?:-(?:dev|alpha|beta|rc)\.\d{1,6})?')
EVENT_NAME = re.compile(r'e-([0-9a-f-]{36})\.json')
BUNDLE_NAME = re.compile(r'Report-Kit-support-\d{8}-[0-9a-f-]{36}\.zip')


def identifier(value):
    if not isinstance(value, str): return False
    try: return str(uuid.UUID(value)) == value and uuid.UUID(value).version == 4
    except ValueError: return False


def stamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z', value):
        raise ValueError('INVALID_EVENT_TIME')
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def versions(value):
    return {k: v for k, v in value.items() if k in POLICY['programs'] and isinstance(v, str)
            and VERSION.fullmatch(v)} if isinstance(value, dict) else {}


def bounded_json(path, limit):
    with path.open('rb') as stream: raw = stream.read(limit+1)
    if len(raw) > limit: raise ValueError('SUPPORT_RECORD_TOO_LARGE')
    return json.loads(raw.decode('utf-8'))


def local_versions():
    observed = {'python':platform.python_version()}
    try:
        manifest = bounded_json(PACKAGE/'plugin.json',8192)
        with (PACKAGE/'VERSION').open('r',encoding='utf-8') as stream: value = stream.read(128).strip()
        if isinstance(manifest,dict) and manifest.get('name') in POLICY['programs']: observed[manifest['name']] = value
    except (OSError,ValueError,UnicodeError): pass
    return versions(observed)


def clean_event(value):
    """Project known fields again at export; never trust an earlier safe label."""
    if not isinstance(value, dict) or type(value.get('schema_version')) is not int or value['schema_version'] != 1:
        raise ValueError('INVALID_EVENT')
    if not all(identifier(value.get(k)) for k in ['run', 'operation', 'event']): raise ValueError('INVALID_EVENT_ID')
    stamp(value.get('at'))
    if type(value.get('sequence')) is not int or not 0 < value['sequence'] < 100000000: raise ValueError('INVALID_SEQUENCE')
    result = {k: value[k] for k in ['schema_version', 'at', 'run', 'operation', 'event', 'sequence']}
    for key, table, fallback in [('component','components','unknown'),('stage','stages','unknown'),
            ('kind','kinds','check'),('result','results','unknown'),('error','errors','UNKNOWN')]:
        result[key] = value.get(key) if value.get(key) in POLICY[table] else fallback
    result['http'] = value.get('http') if type(value.get('http')) is int and value['http'] in POLICY['http'] else 0
    result['versions'] = versions(value.get('versions'))
    return result


def error_code(error):
    # Match exact known exception types, never serialize the exception or its arguments.
    return {'TimeoutError':'TIMEOUT','PermissionError':'ACCESS_DENIED','ConnectionError':'NETWORK',
            'ConnectionRefusedError':'NETWORK','FileNotFoundError':'MISSING_TOOL','ValueError':'INVALID_INPUT',
            'JSONDecodeError':'CORRUPT_DATA','KeyboardInterrupt':'INTERRUPTED','CancelledError':'INTERRUPTED'}.get(type(error).__name__, 'UNKNOWN')


def store(state_dir=None):
    selected = os.fspath(state_dir or os.environ.get('REPORT_SKILLS_STATE_DIR', Path.home()/'.local/state/report-skills'))
    if selected.startswith(('//','\\\\')) or '://' in selected or any(c in selected for c in '\r\n\0'):
        raise ValueError('LOCAL_SUPPORT_PATH_REQUIRED')
    base = Path(selected).expanduser().resolve()
    root = base/'support-v1'
    # The copied fallback may sit beside support-v1 inside the chosen workspace.
    if root.is_relative_to(PACKAGE) or PACKAGE.is_relative_to(root): raise ValueError('SUPPORT_PATH_BOUNDARY')
    if root.is_symlink(): raise ValueError('SUPPORT_PATH_BOUNDARY')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker = root/'owner.json'
    owner = {'owner':'Report Kit support','schema_version':1}
    if not marker.exists():
        if any(root.iterdir()): raise ValueError('SUPPORT_STORE_UNRECOGNIZED')
        with marker.open('x', encoding='utf-8') as stream: json.dump(owner, stream)
        marker.chmod(0o600)
    if marker.is_symlink() or bounded_json(marker,256) != owner:
        raise ValueError('SUPPORT_STORE_UNRECOGNIZED')
    for name in ['events','bundles']:
        path = root/name
        if path.is_symlink(): raise ValueError('SUPPORT_PATH_BOUNDARY')
        path.mkdir(exist_ok=True, mode=0o700)
    return root


def owned_files(root, folder):
    pattern = EVENT_NAME if folder == 'events' else BUNDLE_NAME
    return [p for p in (root/folder).iterdir() if pattern.fullmatch(p.name) and not p.is_symlink() and p.is_file()]


def prune(root, now=None, preserve=None):
    now = now or datetime.now(timezone.utc)
    for folder, days, count, size in [('events',POLICY['retention_days'],POLICY['event_limit'],POLICY['event_bytes_limit']),
                                    ('bundles',POLICY['bundle_days'],POLICY['bundle_limit'],POLICY['bundle_limit']*POLICY['bundle_max_bytes'])]:
        paths = []
        for path in owned_files(root,folder):
            try: paths.append((path,path.stat()))
            except FileNotFoundError: pass
        paths.sort(key=lambda item:(item[0] == preserve, item[1].st_mtime),reverse=True)
        used = 0
        for index, (path,stat) in enumerate(paths):
            used += stat.st_size
            if index >= count or used > size or stat.st_mtime < (now-timedelta(days=days)).timestamp():
                path.unlink(missing_ok=True)


def emit(component, stage, kind, result='unknown', error='NONE', *, operation=None, http=0, program_versions=None, state_dir=None):
    global SEQUENCE, WARNED
    operation = operation if identifier(operation) else str(uuid.uuid4())
    try:
        SEQUENCE += 1
        run = os.environ.get('REPORT_KIT_SUPPORT_RUN_ID', RUN)
        run = run if identifier(run) else RUN
        observed = local_versions()
        if component in {'ui','vk-post','vk-comment','vk-message','vk-stories','instagram','threads','tiktok'}:
            try: observed['playwright'] = importlib.metadata.version('playwright')
            except importlib.metadata.PackageNotFoundError: pass
        observed.update(program_versions or {})
        event = clean_event({'schema_version':1,'at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
            'run':run,'operation':operation,'event':str(uuid.uuid4()),'sequence':SEQUENCE,
            'component':component,'stage':stage,'kind':kind,'result':result,'error':error,'http':http,'versions':observed})
        raw = json.dumps(event,ensure_ascii=False,separators=(',',':')).encode('utf-8')
        if len(raw) > POLICY['event_max_bytes']: raise ValueError('EVENT_TOO_LARGE')
        root = store(state_dir)
        # Each event has its own exclusively created file; a killed writer cannot damage prior events.
        descriptor = os.open(root/'events'/('e-'+event['event']+'.json'), os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        with os.fdopen(descriptor,'wb') as stream: stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        prune(root)
    except Exception:
        if not WARNED: print('REPORT_KIT_SUPPORT_EVENT_NOT_SAVED',file=sys.stderr); WARNED=True
    return operation


LABELS = {'livedune':'LiveDune','ui':'работа с интерфейсом','updates':'обновление Report Kit','setup':'первоначальная настройка',
          'maintenance':'обращение между агентами','qa':'проверка результата','agent':'работа помощника',
          'vk-post':'публикации VK','vk-comment':'комментарии VK','vk-message':'сообщения VK','vk-stories':'истории VK',
          'instagram':'Instagram','threads':'Threads','tiktok':'TikTok','telegram':'Telegram','max':'MAX'}
STAGES = {'queue':'ожидание интерфейса','api':'получение данных','navigation':'открытие страницы','browser_setup':'настройка браузера',
          'capture':'снимок материала','validation':'проверка','replay':'повторная проверка','recovery':'восстановление',
          'preflight':'проверка совместимости','download':'скачивание','stage':'подготовка файлов','activation':'подключение версии',
          'rollback':'возврат версии','request':'запрос помощи','acknowledgement':'подтверждение получения','release':'поиск выпуска','setup':'настройка'}
ERRORS = {'TIMEOUT':'истекло время ожидания','ACCESS_DENIED':'нет необходимого разрешения','NETWORK':'не удалось установить соединение',
          'RATE_LIMIT':'сервис ограничил число запросов','INVALID_INPUT':'не подошли входные данные','MISSING_TOOL':'не найден нужный компонент',
          'INCOMPATIBLE':'обнаружена несовместимость','CORRUPT_DATA':'данные проверки повреждены','INTERRUPTED':'действие прервано',
          'BUDGET_EXHAUSTED':'достигнут разрешённый предел запросов','PROVIDER_ERROR':'сервис сообщил об ошибке',
          'ACTION_UNCERTAIN':'результат действия неизвестен','UNKNOWN':'причина по служебным данным не установлена','NONE':'ошибка не отмечена'}


def action_label(event):
    names = {('qa','validation'):'Проверка результата',('setup','setup'):'Настройка Report Kit',
        ('livedune','api'):'Получение данных из LiveDune',('livedune','recovery'):'Восстановление работы с LiveDune',
        ('ui','queue'):'Ожидание очереди интерфейса',('ui','browser_setup'):'Запуск браузера'}
    return names.get((event['component'],event['stage']),
        STAGES.get(event['stage'],'Действие').capitalize()+' ('+LABELS.get(event['component'],'служебная операция')+')')


def bundle(state_dir=None, now=None):
    root = store(state_dir); now = now or datetime.now(timezone.utc); prune(root,now)
    events, excluded = [], 0
    for path in owned_files(root,'events'):
        try:
            value = bounded_json(path,POLICY['event_max_bytes']); event = clean_event(value)
            excluded += int(value != event)
            if stamp(event['at']) > now+timedelta(minutes=5): raise ValueError('FUTURE_EVENT')
            events.append(event)
        except (ValueError, OSError, UnicodeError, TypeError, KeyError, RecursionError): excluded += 1
    events.sort(key=lambda e:(stamp(e['at']),e['sequence'],e['event']))
    # Fresh aliases prevent correlation across separate archives or accidental stable IDs in supplied records.
    aliases = {}
    for order,event in enumerate(events,1):
        event['order'] = order
        for key in ['run','operation','event']:
            aliases.setdefault(event[key],str(uuid.uuid4())); event[key] = aliases[event[key]]
    unfinished = set()
    for event in events:
        if event['kind'] == 'started': unfinished.add(event['operation'])
        elif event['kind'] == 'finished': unfinished.discard(event['operation'])
    failed = [e for e in events if e['result']=='failure']
    known = [e for e in failed if e['error'] not in {'UNKNOWN','NONE'}]
    last = known[-1] if known else failed[-1] if failed else events[-1] if events else None
    uncertain = sum(e['kind']=='finished' and e['result']=='unknown' for e in events)
    summary = ['Файл для поддержки Report Kit.','',
        ('Сбой на этапе «' if failed else 'Последнее сохранённое действие: «')+action_label(last)+'».' if last else
        'Служебные сведения не сохранились. Определить причину по этому файлу нельзя.',
        'Сохранено событий: '+str(len(events))+'. Незавершённых действий: '+str(len(unfinished))+'.']
    if unfinished: summary.append('Прерванный запуск и ещё выполняющееся действие по этим данным не различаются.')
    if uncertain: summary.append('Действий с неизвестным результатом: '+str(uncertain)+'.')
    if last: summary.append('Отмечено: '+ERRORS[last['error']]+'.')
    checks = [e for e in events if e['kind'] in {'check','recovery','retry'}]
    summary.append('Что уже проверили и попробовали (сохранённых действий: '+str(len(checks))+'):')
    for event in checks[-10:]:
        summary.append('- '+action_label(event)+': '+
                       {'success':'успешно','failure':'не получилось','unknown':'результат неизвестен'}[event['result']]+'.')
    summary.append('Точную причину без дополнительных проверок установить нельзя.')
    summary += ['Исключено повреждённых записей или записей с неподходящими полями: '+str(excluded)+'.',
        'Исходные журналы, ответы сервисов, тексты ошибок, переписки, отчёты, имена, ссылки и пути не собирались.',
        'Данные могли быть удалены по сроку или размеру. Архив не гарантирует полноту диагностики.',
        'Порядок указан по сохранённому времени; для одновременных действий возможна неоднозначность.',
        'Передайте только этот ZIP тому, кто сопровождает Report Kit. Автоматической отправки нет.']
    system_version = platform.mac_ver()[0] if platform.system() == 'Darwin' else platform.win32_ver()[1] if platform.system() == 'Windows' else platform.release()
    environment = {'os':{'Darwin':'macOS','Windows':'Windows','Linux':'Linux'}.get(platform.system(),'unknown'),
        'system_version':system_version if VERSION.fullmatch(system_version) else 'unknown',
        'collector_versions':local_versions(),
        'observed_versions':[e['versions'] for e in events if e['versions']],
        'limitations':'Only versions observed by the collector or selected components; no machine/user/device identity or command output.'}
    manifest = {'schema_version':1,'bundle':str(uuid.uuid4()),'created_at':now.isoformat().replace('+00:00','Z'),
        'events':len(events),'excluded_records':excluded,'unfinished_operations':len(unfinished),'unknown_outcomes':uncertain,'raw_sources_included':False,
        'retention':{k:POLICY[k] for k in ['retention_days','event_limit','event_bytes_limit','bundle_days','bundle_limit','bundle_max_bytes']}}
    path = root/'bundles'/('Report-Kit-support-'+now.strftime('%Y%m%d')+'-'+manifest['bundle']+'.zip')
    created = False
    try:
        with path.open('xb') as target:
            created = True
            with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                for name,value in [('ПРОЧИТАЙТЕ.txt','\n'.join(summary)+'\n'),('events.json',events),('environment.json',environment),('manifest.json',manifest)]:
                    archive.writestr(name,value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2))
        path.chmod(0o600)
        if path.stat().st_size > POLICY['bundle_max_bytes']: raise ValueError('BUNDLE_SIZE_LIMIT')
    except Exception:
        if created: path.unlink(missing_ok=True)
        raise
    prune(root,now,preserve=path)
    return path


def prepare_fallback(destination, state_dir, python=None):
    """A new chosen private folder only; never install a plugin or overwrite another file."""
    destination = Path(destination).expanduser().resolve()
    root = store(state_dir)
    if destination.exists() or destination.is_relative_to(PACKAGE) or PACKAGE.is_relative_to(destination) \
            or destination.is_relative_to(root) or root.is_relative_to(destination):
        raise ValueError('FALLBACK_PATH_BOUNDARY')
    payloads = {'scripts/support_bundle.py':Path(__file__).read_bytes(),
        'scripts/support-policy.json':Path(__file__).with_name('support-policy.json').read_bytes(),
        'VERSION':(PACKAGE/'VERSION').read_bytes(), 'plugin.json':(PACKAGE/'plugin.json').read_bytes(),
        'support-location.json':json.dumps({'state_dir':str(root.parent)}).encode('utf-8'),
        'КАК ПЕРЕДАТЬ.txt':('Дважды нажмите файл «Подготовить файл поддержки». Откроется папка с ZIP.\n'
                           'Перешлите только этот ZIP сопровождающему Report Kit. Другие файлы из этой папки не отправляйте.\n'
                           'Вход в аккаунты, работающий агент и интернет для сбора не нужны. Нужен установленный Python.\n').encode('utf-8')}
    if python is not None:
        python = Path(python).resolve()
        if not python.is_file() or any(c in str(python) for c in '\r\n\"%!'): raise ValueError('FALLBACK_RUNTIME_INVALID')
        payloads['runtime-python.txt'] = (str(python)+'\n').encode('utf-8')
        payloads['КАК ПЕРЕДАТЬ.txt'] = payloads['КАК ПЕРЕДАТЬ.txt'].decode('utf-8').replace('Нужен установленный Python.', 'Используется заранее подготовленный компонент Report Kit; устанавливать Python вручную не нужно.').encode('utf-8')
    if sys.platform == 'win32':
        payloads['Подготовить файл поддержки.cmd'] = WINDOWS_LAUNCHER.encode('utf-8')
    else:
        payloads['Подготовить файл поддержки.command'] = MAC_LAUNCHER.encode('utf-8')
    destination.mkdir(parents=True,mode=0o700)
    for name,raw in payloads.items():
        path = destination/name; path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with path.open('xb') as stream: stream.write(raw)
        path.chmod(0o700 if path.suffix == '.command' else 0o600)
    return destination


WINDOWS_LAUNCHER = '''@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "%~dp0runtime-python.txt" goto system
set /p RK_SUPPORT_PYTHON=<"%~dp0runtime-python.txt"
"%RK_SUPPORT_PYTHON%" -I -B "%~dp0scripts\\support_bundle.py" --saved-state --open-folder
goto end
:system
where py >nul 2>nul
if errorlevel 1 goto python
py -3 -I -B "%~dp0scripts\\support_bundle.py" --saved-state --open-folder
goto end
:python
where python >nul 2>nul
if errorlevel 1 goto missing
python -I -B "%~dp0scripts\\support_bundle.py" --saved-state --open-folder
goto end
:missing
echo Не найден компонент для сбора файла. Сообщите поддержке код SUPPORT_PYTHON_MISSING. Ничего не отправлено.
:end
pause
'''
MAC_LAUNCHER = '''#!/bin/sh
cd -- "$(dirname -- "$0")" || exit 1
if [ -f ./runtime-python.txt ]; then
  IFS= read -r rk_support_python < ./runtime-python.txt
  "$rk_support_python" -I -B ./scripts/support_bundle.py --saved-state --open-folder
elif command -v python3 >/dev/null 2>&1; then
  python3 -I -B ./scripts/support_bundle.py --saved-state --open-folder
else
  printf '%s\\n' 'Не найден компонент для сбора файла. Сообщите поддержке код SUPPORT_PYTHON_MISSING. Ничего не отправлено.'
fi
'''


def main():
    parser = argparse.ArgumentParser(description='Подготовить один файл для поддержки. Ничего не отправляет.')
    parser.add_argument('--state-dir',type=Path)
    parser.add_argument('--open-folder',action='store_true')
    parser.add_argument('--saved-state',action='store_true')
    parser.add_argument('--prepare-fallback',type=Path)
    parser.add_argument('--python',type=Path,help='Проверенный компонент Report Kit для запасного запуска')
    sub = parser.add_subparsers(dest='action')
    event = sub.add_parser('record')
    for name,options in [('component',POLICY['components']),('stage',POLICY['stages']),('kind',POLICY['kinds']),('result',POLICY['results']),('error',POLICY['errors'])]:
        event.add_argument('--'+name,choices=options,required=True)
    event.add_argument('--operation')
    args = parser.parse_args()
    try:
        if args.saved_state:
            saved = PACKAGE/'support-location.json'
            if saved.exists():
                if saved.is_symlink() or saved.stat().st_size > 8192: raise ValueError('SUPPORT_LOCATION_INVALID')
                value = bounded_json(saved,8192)
                if not isinstance(value,dict) or set(value) != {'state_dir'} or not isinstance(value['state_dir'],str): raise ValueError('SUPPORT_LOCATION_INVALID')
                args.state_dir = value['state_dir']
        if args.prepare_fallback:
            print('Запасной способ подготовки файла сохранён: '+str(prepare_fallback(args.prepare_fallback,args.state_dir,args.python))); return 0
        if args.action == 'record':
            print(emit(args.component,args.stage,args.kind,args.result,args.error,operation=args.operation,state_dir=args.state_dir)); return 0
        path = bundle(args.state_dir)
        print('Файл для поддержки готов: '+str(path))
        print('Перешлите этот ZIP сопровождающему Report Kit. Больше ничего прикладывать не нужно.')
        if args.open_folder:
            try:
                if sys.platform == 'win32': os.startfile(path.parent)
                elif sys.platform == 'darwin': subprocess.run(['open','-R',str(path)],check=False)
            except OSError: print('Папку не удалось открыть автоматически. Путь к готовому ZIP указан выше.')
        return 0
    except Exception:
        print('Не удалось подготовить файл поддержки. Передайте сопровождающему код SUPPORT_BUNDLE_FAILED. Исходники и отчёты не изменены.',file=sys.stderr)
        return 1


if __name__ == '__main__': raise SystemExit(main())
