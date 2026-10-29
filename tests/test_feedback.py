"""Preferences belong to one reader; votes refer to immutable editions and URLs."""
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from pypdf import PdfReader
from test_giornale import g, fixture, CFG, TODAY


class Feedback(unittest.TestCase):
    def config(self, temp):
        cfg=dict(CFG,version=1,engine='codex',binary=sys.executable,data_dir=str(Path(temp).resolve()),at='06:00',interests=['AI per il lavoro'],sources=['https://example.com/news'],profile='',timeout_seconds=30,print_enabled=False)
        g.write_json(Path(temp)/'config.json',cfg)
        return cfg

    def cli(self,temp,*args,ok=True):
        result=subprocess.run([sys.executable,str(g.ROOT/'scripts/giornale.py'),'feedback','--data-dir',str(temp),*args],text=True,capture_output=True)
        if ok:self.assertEqual(result.returncode,0,result.stderr)
        return result

    def test_exclusion_persists_new_process_prompt_and_can_be_undone(self):
        with tempfile.TemporaryDirectory(prefix='preferenze con spazi ') as temp:
            self.config(temp)
            self.cli(temp,'--exclude','Copilot')
            shown=json.loads(self.cli(temp,'--show').stdout)
            self.assertEqual(shown['excluded_topics'],['Copilot'])
            cfg=g.load_config(temp)
            prompt=g.build_prompt(cfg,g.now_local(cfg))
            self.assertIn('Copilot',prompt);self.assertIn('ESCLUSIONI',prompt)
            d=fixture();d['articles'][0]['title']='GitHub Copilot lavora nelle app'
            with self.assertRaisesRegex(g.GiornaleError,'Copilot'):g.validate_edition(d,cfg,TODAY)
            self.cli(temp,'--include','copilot')
            g.validate_edition(d,g.load_config(temp),TODAY)

    def test_topic_is_whole_text_phrase_not_provider_domain(self):
        cfg=dict(CFG,excluded_topics=['Copilot','calcio'])
        for title in ['GITHUB COPILOT nelle app','microsoft copilot nel lavoro','Nuove regole del calcio']:
            d=fixture();d['articles'][0]['title']=title
            with self.subTest(title=title),self.assertRaises(g.GiornaleError):g.validate_edition(d,cfg,TODAY)
        for title in ['Claude per la formazione','ChatGPT introduce strumenti','GitHub migliora la sicurezza']:
            d=fixture();d['articles'][0].update(title=title,source_url='https://github.blog/security/allowed')
            g.validate_edition(d,cfg,TODAY)
        d=fixture();d['articles'][0]['body']+=' Microsoft Copilot.'
        with tempfile.TemporaryDirectory() as temp,self.assertRaises(g.GiornaleError):g.render_pdf(d,Path(temp)/'blocked.pdf',cfg)

    def test_vote_is_idempotent_url_bound_and_not_a_provider_ban(self):
        self.assertTrue(hasattr(g,'save_snapshot'),'Manca riferimento immutabile dell’edizione')
        with tempfile.TemporaryDirectory() as temp:
            cfg=self.config(temp);d=fixture();eid=g.save_snapshot(Path(temp),d)
            ref=f'{TODAY.isoformat()}:{eid}'
            self.cli(temp,'--article','3','--vote','useful','--edition',ref)
            first=g.load_config(temp)
            self.cli(temp,'--article','3','--vote','useful','--edition',ref)
            second=g.load_config(temp)
            self.assertEqual(first,second)
            self.assertEqual(len(second['feedback']),1)
            self.assertEqual(second['feedback'][0]['source_url'],d['articles'][2]['source_url'])
            self.assertEqual(second['feedback'][0]['edition_id'],eid)
            self.assertEqual(second.get('excluded_topics',[]),[])
            self.assertIn(d['articles'][2]['title'],g.build_prompt(second,g.now_local(second)))
            reordered=copy.deepcopy(d);reordered['articles'].reverse();eid2=g.save_snapshot(Path(temp),reordered)
            self.assertNotEqual(eid,eid2)
            self.cli(temp,'--article','3','--vote','not-useful','--edition',ref)
            vote=g.load_config(temp)['feedback'][0]
            self.assertEqual(vote['source_url'],d['articles'][2]['source_url'])
            self.assertEqual(vote['vote'],'not-useful')
            self.assertNotEqual(self.cli(temp,'--article','2','--vote','useful','--edition',TODAY.isoformat(),ok=False).returncode,0)
            self.assertNotEqual(self.cli(temp,'--article','7','--vote','useful','--edition',ref,ok=False).returncode,0)
            self.cli(temp,'--article','3','--clear-vote','--edition',ref)
            self.assertEqual(g.load_config(temp)['feedback'],[])

    def test_default_vote_uses_latest_edition_date_not_copy_time(self):
        import os
        import datetime as dt
        with tempfile.TemporaryDirectory() as temp:
            self.config(temp);current=fixture();current_id=g.save_snapshot(Path(temp),current)
            older=copy.deepcopy(current);older['date']=(TODAY-dt.timedelta(days=1)).isoformat();older['articles'][0]['source_url']='https://example.com/older'
            old_id=g.save_snapshot(Path(temp),older)
            old_path=Path(temp)/'editions'/older['date']/f'edition-{old_id}.json'
            os.utime(old_path,(4_000_000_000,4_000_000_000))
            self.cli(temp,'--article','1','--vote','useful')
            vote=g.load_config(temp)['feedback'][0]
            self.assertEqual(vote['edition_id'],current_id)
            self.assertEqual(vote['source_url'],current['articles'][0]['source_url'])

    def test_two_processes_keep_both_preferences_and_history_is_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg=self.config(temp)
            cfg['feedback']=[{'edition_date':'2020-01-01','edition_id':str(i),'source_url':f'https://example.com/old/{i}','title':'Vecchio voto','section':'Prova','vote':'useful','updated_at':'2020-01-01T00:00:00+00:00'} for i in range(100)]
            g.write_json(Path(temp)/'config.json',cfg)
            cmds=[[sys.executable,str(g.ROOT/'scripts/giornale.py'),'feedback','--data-dir',temp,'--exclude',topic] for topic in ['Copilot','Calcio']]
            processes=[subprocess.Popen(c,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for c in cmds]
            for process in processes:
                out,err=process.communicate(timeout=15);self.assertEqual(process.returncode,0,err)
            updated=g.load_config(temp);self.assertEqual(set(updated['excluded_topics']),{'Copilot','Calcio'})
            eid=g.save_snapshot(Path(temp),fixture())
            self.cli(temp,'--article','1','--vote','useful','--edition',f'{TODAY.isoformat()}:{eid}')
            self.assertEqual(len(g.load_config(temp)['feedback']),100)

    def test_installer_preserves_existing_preferences_and_feedback(self):
        import argparse
        with tempfile.TemporaryDirectory() as temp:
            project=Path(temp)/'project';data=Path(temp)/'my data';data.mkdir()
            cfg=self.config(data);cfg.update(excluded_topics=['Calcio'],feedback=[{'source_url':'https://example.com/a','vote':'useful'}]);g.write_json(data/'config.json',cfg)
            before=(data/'config.json').read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                g.install(argparse.Namespace(scope='project',project=str(project),engine='both'))
                g.install(argparse.Namespace(scope='project',project=str(project),engine='both'))
            self.assertEqual(before,(data/'config.json').read_bytes())

    def test_pdf_has_numbers_edition_and_no_logo_badge(self):
        with tempfile.TemporaryDirectory() as temp:
            d=fixture();out=Path(temp)/'numbered.pdf';report=g.render_pdf(d,out,CFG)
            page=PdfReader(out).pages[0];text=' '.join(page.extract_text().split())
            self.assertEqual(len(PdfReader(out).pages),1)
            self.assertEqual(len(page.images),0)
            self.assertIn('1 ·',text);self.assertIn('5 ·',text)
            self.assertIn('Edizione',text);self.assertIn('notizia 3',text)
            self.assertGreaterEqual(report['min_body_font'],9)


if __name__=='__main__':unittest.main()
