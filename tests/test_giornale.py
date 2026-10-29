"""Behavior tests: private data, dates, concurrency, engine boundary, layout, printing."""
import argparse
import contextlib
import copy
import datetime as dt
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import venv
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('giornale',Path(__file__).resolve().parents[1]/'scripts/giornale.py')
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
CFG={'timezone':'Europe/Rome','max_window_hours':168}
TODAY=dt.datetime.now(g.zone('Europe/Rome')).date()


def fixture(count=5):
    d=json.loads((g.ROOT/'examples/edition-demo.json').read_text())
    d.update(date=TODAY.isoformat(),status='ok',note='Notizie dalle ultime 48 ore',coverage='complete',audit='Fonti primarie consultate nella prova sintetica.')
    if count==4: d['articles']=d['articles'][:4]
    if count==6: d['articles'].append(copy.deepcopy(d['articles'][-1]))
    sizes={4:[170,130,140,140],5:[155,110,90,90,90],6:[150,110,80,80,80,80]}[count]
    sentence='Una fonte primaria descrive il cambiamento e chiarisce i limiti della prova senza promettere risultati universali. '
    for i,(a,size) in enumerate(zip(d['articles'],sizes)):
        a.update(title=['Un laboratorio apre i suoi dati','Una biblioteca prova nuovi orari','Misurare prima di cambiare','Un archivio diventa consultabile','Un gruppo racconta la sua prova','La ricerca guarda il territorio'][i],
                 source_url=f'https://example.com/news/{i}',published_date=TODAY.isoformat())
        a['body']=' '.join((sentence*20).split()[:size])
        a['subtitle']='Un esempio misurabile con una fonte diretta.' if i==0 else ''
    return d


class Validation(unittest.TestCase):
    def test_live_fixture_and_four_six_long_articles(self):
        from pypdf import PdfReader
        for count in (4,6):
            d=fixture(count)
            g.validate_edition(d,CFG,TODAY)
            with tempfile.TemporaryDirectory(prefix='giornale spazi ') as temp:
                out=Path(temp)/'numero con spazi.pdf'
                report=g.render_pdf(d,out,CFG)
                self.assertEqual(len(PdfReader(out).pages),1)
                self.assertGreaterEqual(report['min_body_font'],9)
                for block in report['blocks']:
                    self.assertLessEqual(block['bottom'],794)
                for a in d['articles']:
                    self.assertIn(a['title'],' '.join(PdfReader(out).pages[0].extract_text().split()))

    def test_official_image_layout_has_caption_and_never_overlaps_article(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp:
            image=Path(temp)/'fixture.jpg';Image.new('RGB',(1200,700),'#18211f').save(image)
            d=fixture();d['articles'][0].update(image_url='https://example.com/official.jpg',image_credit='Schermata dimostrativa della fonte ufficiale')
            report=g.render_pdf(d,Path(temp)/'with-image.pdf',CFG,image)
            caption=next(b for b in report['blocks'] if b['role']=='image_credit')
            second=[b for b in report['blocks'] if b['role']=='article_1']
            self.assertLess(caption['bottom'],min(b['top'] for b in second))
            self.assertGreaterEqual(report['min_body_font'],9)

    def test_stale_future_and_false_edition_date_fail(self):
        for date in (TODAY-dt.timedelta(days=20),TODAY+dt.timedelta(days=1)):
            d=fixture();d['articles'][0]['published_date']=date.isoformat()
            with self.assertRaises(g.GiornaleError):g.validate_edition(d,CFG,TODAY)
        d=fixture();d['date']='2001-01-01'
        with self.assertRaises(g.GiornaleError):g.validate_edition(d,CFG,TODAY)

    def test_invalid_json_missing_fields_duplicate_and_extended_window(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'bad.json';path.write_text('{')
            with self.assertRaises(g.GiornaleError):g.read_json(path)
        for mutate in (lambda d:d.pop('date'),lambda d:d['articles'][1].update(source_url=d['articles'][0]['source_url']+'?utm_source=x')):
            d=fixture();mutate(d)
            with self.assertRaises(g.GiornaleError):g.validate_edition(d,CFG,TODAY)
        d=fixture();d.update(window_hours=168,note='')
        with self.assertRaises(g.GiornaleError):g.validate_edition(d,CFG,TODAY)

    def test_no_updates_is_explicit_not_filler(self):
        d={'date':TODAY.isoformat(),'status':'no_updates','window_hours':168,'note':'Nessun aggiornamento verificato nelle fonti confermate.','coverage':'complete','audit':'Ricerca completa nelle fonti configurate.','articles':[]}
        g.validate_edition(d,CFG,TODAY)
        with tempfile.TemporaryDirectory() as temp:
            result=g.render_pdf(d,Path(temp)/'empty.pdf',CFG)
            self.assertEqual(result['pages'],1)
        d['articles']=fixture()['articles']
        with self.assertRaises(g.GiornaleError):g.validate_edition(d,CFG,TODAY)

    def test_private_or_non_http_urls_refused(self):
        urls=['file:///etc/passwd','data:image/png;base64,xx','http://localhost/a','http://127.0.0.1/a','http://10.0.0.1/a','http://169.254.169.254/latest','http://[::1]/','https://user:pass@example.com/a','https://example.com:8443/a','https://printer.local/a']
        for url in urls:
            with self.subTest(url=url),self.assertRaises(g.GiornaleError):g.url_public(url)
        with patch.object(g.socket,'getaddrinfo',return_value=[(None,None,None,None,('10.1.1.1',443))]):
            with self.assertRaises(g.GiornaleError):g.url_public('https://example.com/image.png',resolve=True)


class NoteContract(unittest.TestCase):
    def test_schema_note_budget_is_explicit(self):
        schema=g.read_json(g.ROOT/'scripts/edition.schema.json')
        self.assertEqual(schema['properties']['note'].get('maxLength'),220)
        self.assertIn('coverage',schema['required']);self.assertIn('audit',schema['required'])
        self.assertIn('220',g.build_prompt(dict(timezone='Europe/Rome',interests=['Ambiente'],sources=['https://example.com'],max_window_hours=168,profile=''),dt.datetime.now(g.zone('Europe/Rome'))))

    def test_recover_retains_827_char_audit_and_original_immutable(self):
        self.assertTrue(hasattr(g,'recover_note'),'Manca recupero esplicito e tracciato della nota')
        original_note=('Oracle e OpenAI: apertura diretta rifiutata HTTP 403; la lettura è parziale. ' * 20)[:827]
        with tempfile.TemporaryDirectory() as temp:
            raw=Path(temp)/'model.json';derived=Path(temp)/'edition.json'
            d=fixture();d.pop('coverage',None);d.pop('audit',None);d['note']=original_note
            g.write_json(raw,d);before=raw.read_bytes()
            args=argparse.Namespace(input=str(raw),output=str(derived),note='Oracle e OpenAI: HTTP 403; verifiche limitate agli estratti indicizzati. Dettagli nel JSON.',coverage='partial',timezone='Europe/Rome')
            with contextlib.redirect_stdout(io.StringIO()):g.recover_note(args)
            out=g.read_json(derived)
            self.assertLessEqual(len(out['note']),220);self.assertEqual(out['coverage'],'partial')
            self.assertIn(original_note,out['audit']);self.assertIn(g.sha(raw),out['audit'])
            self.assertEqual(before,raw.read_bytes());g.validate_edition(out,CFG,TODAY)
            with self.assertRaises(g.GiornaleError):g.recover_note(args)

    def test_partial_403_is_visible_and_never_false_no_updates(self):
        from pypdf import PdfReader
        d=fixture();d.update(coverage='partial',audit='OpenAI HTTP 403: lettura incompleta, fonte esclusa.',note='Una fonte non è accessibile: i dettagli completi sono nel JSON.')
        g.validate_edition(d,CFG,TODAY)
        with tempfile.TemporaryDirectory() as temp:
            pdf=Path(temp)/'partial.pdf';g.render_pdf(d,pdf,CFG)
            self.assertIn('LETTURA PARZIALE',PdfReader(pdf).pages[0].extract_text())
        d.update(status='no_updates',articles=[])
        with self.assertRaises(g.GiornaleError):g.validate_edition(d,CFG,TODAY)
        d.update(coverage='blocked')
        with self.assertRaises(g.GiornaleError):g.validate_edition(d,CFG,TODAY)

    def test_403_audit_cannot_claim_complete_no_updates(self):
        d=fixture();d.update(status='no_updates',articles=[],coverage='complete',audit='OpenAI: HTTP 403, la fonte non si apre.',note='Non trovo notizie.')
        with self.assertRaisesRegex(g.GiornaleError,'[Pp]arziale'):g.validate_edition(d,CFG,TODAY)


class InstallAndConfigure(unittest.TestCase):
    def test_install_both_spaces_repeat_and_user_change_preserved(self):
        with tempfile.TemporaryDirectory(prefix='progetto con spazi ') as temp:
            args=argparse.Namespace(scope='project',project=temp,engine='both')
            with contextlib.redirect_stdout(io.StringIO()):g.install(args)
            target=Path(temp)/'.agents/skills/leaderai-giornale'
            first=g.sha(target/'SKILL.md')
            with contextlib.redirect_stdout(io.StringIO()):g.install(args)
            self.assertEqual(first,g.sha(target/'SKILL.md'))
            self.assertTrue((Path(temp)/'.claude/skills/leaderai-giornale/SKILL.md').is_file())
            (target/'SKILL.md').write_text('Modifica della persona')
            with self.assertRaises(g.GiornaleError):g.install(args)
            self.assertEqual((target/'SKILL.md').read_text(),'Modifica della persona')
            self.assertFalse((Path(temp)/'config.json').exists())

    def test_profile_missing_and_present_no_config_in_source(self):
        with tempfile.TemporaryDirectory(prefix='config con spazi ') as temp:
            base=Path(temp)
            def args(path,profile=None):
                return argparse.Namespace(data_dir=str(path),engine='codex',binary=sys.executable,interest=['Ambiente'],source=['https://example.com/news'],profile=profile,timezone='Europe/Rome',at='06:00')
            with contextlib.redirect_stdout(io.StringIO()):g.init_config(args(base/'senza profilo'))
            cfg=g.load_config(base/'senza profilo')
            self.assertEqual(cfg['profile'],'');self.assertFalse(cfg['print_enabled'])
            self.assertIn('Ambiente',g.build_prompt(cfg,dt.datetime.now(g.zone('Europe/Rome'))))
            profile=base/'preferenze.md';profile.write_text('Profilo sintetico: ambiente e biblioteche.')
            with contextlib.redirect_stdout(io.StringIO()):g.init_config(args(base/'con profilo',str(profile)))
            cfg=g.load_config(base/'con profilo')
            self.assertIn('biblioteche',g.build_prompt(cfg,dt.datetime.now(g.zone('Europe/Rome'))))
            with self.assertRaises(g.GiornaleError):g.init_config(args(base/'manca',str(base/'assente.md')))
            profile.unlink()
            with self.assertRaises(g.GiornaleError):g.build_prompt(cfg,dt.datetime.now(g.zone('Europe/Rome')))

    def test_scheduler_is_plan_only_absolute_argv(self):
        with tempfile.TemporaryDirectory() as temp:
            installed=Path(temp)/'skill installata'; (installed/'scripts').mkdir(parents=True); (installed/'.install.json').write_text('{}'); (installed/'scripts/giornale.py').write_text('# installed')
            venv_python=Path(temp)/'.venv/bin/python';venv_python.parent.mkdir(parents=True);venv_python.symlink_to(sys.executable)
            cfg=dict(CFG,version=1,engine='codex',binary=sys.executable,data_dir=str(Path(temp).resolve()),at='06:00',runner_path=str(installed/'scripts/giornale.py'))
            g.write_json(Path(temp)/'config.json',cfg)
            before=set(Path(temp).iterdir());out=io.StringIO()
            with patch.object(g.sys,'executable',str(venv_python)),contextlib.redirect_stdout(out):g.schedule_plan(argparse.Namespace(data_dir=temp))
            plan=json.loads(out.getvalue())
            self.assertFalse(plan['active']);self.assertTrue(Path(plan['argv'][0]).is_absolute())
            self.assertEqual(plan['argv'][0],str(venv_python));self.assertEqual(plan['argv'][1],cfg['runner_path'])
            self.assertEqual(before,set(Path(temp).iterdir()))

    def test_venv_interpreter_keeps_venv_only_dependency(self):
        with tempfile.TemporaryDirectory(prefix='venv con spazi ') as temp:
            env=Path(temp)/'.venv';venv.EnvBuilder(with_pip=False).create(env)
            py=env/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
            site=subprocess.check_output([str(py),'-c','import sysconfig; print(sysconfig.get_path("purelib"))'],text=True).strip()
            (Path(site)/'giornale_venv_probe.py').write_text('VALUE="solo venv"')
            self.assertEqual(subprocess.check_output([str(py),'-c','import giornale_venv_probe; print(giornale_venv_probe.VALUE)'],text=True).strip(),'solo venv')
            installed=Path(temp)/'skill';(installed/'scripts').mkdir(parents=True);(installed/'.install.json').write_text('{}');(installed/'scripts/giornale.py').write_text('# installed')
            cfg=dict(CFG,version=1,engine='codex',binary=sys.executable,data_dir=str(Path(temp).resolve()),at='06:00',runner_path=str(installed/'scripts/giornale.py'))
            g.write_json(Path(temp)/'config.json',cfg);out=io.StringIO()
            with patch.object(g.sys,'executable',str(py)),contextlib.redirect_stdout(out):g.schedule_plan(argparse.Namespace(data_dir=temp))
            planned=json.loads(out.getvalue())['argv'][0]
            self.assertEqual(subprocess.check_output([planned,'-c','import giornale_venv_probe; print(giornale_venv_probe.VALUE)'],text=True).strip(),'solo venv')


class RunAndPrint(unittest.TestCase):
    def make_config(self,temp,engine='codex'):
        cfg=dict(CFG,version=1,engine=engine,binary=sys.executable,data_dir=str(Path(temp).resolve()),at='06:00',interests=['Ricerca'],sources=['https://example.com'],profile='',timeout_seconds=30,print_enabled=False)
        g.write_json(Path(temp)/'config.json',cfg);return cfg

    def test_command_boundary_and_claude_structured_flags(self):
        cfg=dict(engine='codex',binary=sys.executable)
        cmd=g.engine_command(cfg,g.ROOT/'scripts/edition.schema.json',Path('/tmp/out con spazi.json'))
        self.assertIn('read-only',cmd);self.assertIn('web_search="live"',cmd);self.assertIn('--output-schema',cmd)
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox',cmd)
        cfg['engine']='claude';cmd=g.engine_command(cfg,g.ROOT/'scripts/edition.schema.json',Path('/tmp/out.json'))
        self.assertIn('WebSearch,WebFetch',cmd);self.assertIn('--json-schema',cmd);self.assertEqual(cmd[cmd.index('--allowedTools')+1],'WebSearch,WebFetch')
        self.assertNotIn('--bare',cmd);self.assertNotIn('Bash',','.join(cmd))

    def test_one_run_duplicate_lock_and_no_print(self):
        with tempfile.TemporaryDirectory(prefix='run con spazi ') as temp:
            self.make_config(temp)
            seen=[]
            def fake(cmd,**kwargs):
                seen.append((cmd,kwargs))
                self.assertNotIn('shell',kwargs)
                self.assertNotIn('OPENAI_API_KEY',kwargs['env']);self.assertNotIn('ANTHROPIC_API_KEY',kwargs['env'])
                self.assertTrue(str(kwargs['cwd']).startswith(str(Path(temp).resolve())))
                self.assertIn('Profilo approvato',kwargs['input'])
                g.write_json(cmd[cmd.index('-o')+1],fixture())
                return subprocess.CompletedProcess(cmd,0)
            args=argparse.Namespace(data_dir=temp,force=False,resume_render=False)
            with patch.object(g.subprocess,'run',side_effect=fake),contextlib.redirect_stdout(io.StringIO()):
                g.run_edition(args);g.run_edition(args)
            self.assertEqual(len(seen),1)
            receipt=g.read_json(Path(temp)/'editions'/TODAY.isoformat()/'receipt.json')
            self.assertEqual(receipt['status'],'ready');self.assertEqual(receipt['print'],'off')
            self.assertFalse(list(Path(temp).rglob('*.print.json')))
            with g.exclusive_lock(temp):
                with self.assertRaises(g.GiornaleError):g.run_edition(args)

    def test_failure_recorded_and_claude_envelope(self):
        with tempfile.TemporaryDirectory() as temp:
            self.make_config(temp)
            with patch.object(g.subprocess,'run',return_value=subprocess.CompletedProcess([],1)),self.assertRaises(g.GiornaleError):
                g.run_edition(argparse.Namespace(data_dir=temp,force=False,resume_render=False))
            receipt=Path(temp)/'editions'/TODAY.isoformat()/'receipt.json'
            self.assertEqual(g.read_json(receipt)['status'],'failed')
        with tempfile.TemporaryDirectory() as temp:
            self.make_config(temp,'claude')
            def fake(cmd,**kwargs):
                kwargs['stdout'].write(json.dumps({'structured_output':fixture()}));kwargs['stdout'].flush()
                return subprocess.CompletedProcess(cmd,0)
            with patch.object(g.subprocess,'run',side_effect=fake),contextlib.redirect_stdout(io.StringIO()):
                g.run_edition(argparse.Namespace(data_dir=temp,force=False,resume_render=False))
            self.assertEqual(g.read_json(Path(temp)/'editions'/TODAY.isoformat()/'receipt.json')['status'],'ready')

    def test_resume_render_reuses_research_without_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            self.make_config(temp)
            folder=Path(temp)/'editions'/TODAY.isoformat();folder.mkdir(parents=True)
            g.write_json(folder/'edition.json',fixture())
            g.write_json(folder/'receipt.json',{'status':'failed','job':'original-research'})
            with patch.object(g.subprocess,'run') as run,contextlib.redirect_stdout(io.StringIO()):
                g.run_edition(argparse.Namespace(data_dir=temp,force=False,resume_render=True))
            run.assert_not_called()
            self.assertEqual(g.read_json(folder/'receipt.json')['status'],'ready')
            with self.assertRaises(g.GiornaleError):g.run_edition(argparse.Namespace(data_dir=temp,force=False,resume_render=True))

    def test_claude_permission_denial_is_failure_not_empty_news(self):
        with tempfile.TemporaryDirectory() as temp:
            self.make_config(temp,'claude')
            def fake(cmd,**kwargs):
                kwargs['stdout'].write(json.dumps({'structured_output':{'date':TODAY.isoformat(),'status':'no_updates','window_hours':48,'note':'Non trovo aggiornamenti','coverage':'complete','audit':'','articles':[]},'permission_denials':[{'tool_name':'WebSearch'}]}));kwargs['stdout'].flush()
                return subprocess.CompletedProcess(cmd,0)
            with patch.object(g.subprocess,'run',side_effect=fake),self.assertRaises(g.GiornaleError):
                g.run_edition(argparse.Namespace(data_dir=temp,force=False,resume_render=False))
            self.assertEqual(g.read_json(Path(temp)/'editions'/TODAY.isoformat()/'receipt.json')['status'],'failed')

    def test_partial_run_preserves_audit_and_receipt_status(self):
        with tempfile.TemporaryDirectory() as temp:
            self.make_config(temp)
            audit=('Fonte primaria: HTTP 403, accesso incompleto. '*20)[:827]
            def fake(cmd,**kwargs):
                data=fixture();data.update(coverage='partial',audit=audit,note='Una fonte primaria ha rifiutato accesso HTTP 403. Audit completo nel JSON.')
                g.write_json(cmd[cmd.index('-o')+1],data)
                return subprocess.CompletedProcess(cmd,0)
            with patch.object(g.subprocess,'run',side_effect=fake),contextlib.redirect_stdout(io.StringIO()):
                g.run_edition(argparse.Namespace(data_dir=temp,force=False,resume_render=False))
            folder=Path(temp)/'editions'/TODAY.isoformat()
            receipt=g.read_json(folder/'receipt.json')
            self.assertEqual(receipt['status'],'partial');self.assertEqual(receipt['coverage'],'partial')
            self.assertEqual(g.read_json(receipt['audit_file'])['audit'],audit)
            self.assertEqual(receipt['print'],'off')

    def test_print_queue_is_not_physical_and_never_repeated(self):
        with tempfile.TemporaryDirectory() as temp:
            self.make_config(temp)
            pdf=Path(temp)/'editions'/TODAY.isoformat()/'test.pdf';pdf.parent.mkdir(parents=True);pdf.write_bytes(b'%PDF-1.4 test')
            args=argparse.Namespace(data_dir=temp,pdf=str(pdf),confirm=True)
            out=io.StringIO()
            with patch.object(g.shutil,'which',return_value='/usr/bin/lp'),patch.object(g.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'request id is Printer-42','')) as run,contextlib.redirect_stdout(out):
                g.print_pdf(args)
                with self.assertRaises(g.GiornaleError):g.print_pdf(args)
            self.assertEqual(run.call_count,1)
            result=json.loads(out.getvalue());self.assertEqual(result['status'],'queued');self.assertFalse(result['physical_print_verified'])

    def test_ambiguous_print_never_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            self.make_config(temp)
            pdf=Path(temp)/'editions'/TODAY.isoformat()/'test.pdf';pdf.parent.mkdir(parents=True);pdf.write_bytes(b'%PDF-1.4 test')
            args=argparse.Namespace(data_dir=temp,pdf=str(pdf),confirm=True)
            with patch.object(g.shutil,'which',return_value='/usr/bin/lp'),patch.object(g.subprocess,'run',side_effect=subprocess.TimeoutExpired('lp',30)) as run,contextlib.redirect_stdout(io.StringIO()):
                g.print_pdf(args)
                with self.assertRaises(g.GiornaleError):g.print_pdf(args)
            self.assertEqual(run.call_count,1);self.assertEqual(g.read_json(pdf.with_suffix('.print.json'))['status'],'unknown')


if __name__=='__main__':unittest.main()
