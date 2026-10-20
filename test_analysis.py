import json
import unittest
import analysis


def event(ns, content=None, reasoning=None):
    delta={}
    if content is not None: delta['content']=content
    if reasoning is not None: delta['reasoning_content']=reasoning
    return {'elapsed_ns':ns,'data':json.dumps({'choices':[{'delta':delta}]})}


def rec(**kw):
    d={'request_id':'r','phase':'formal','kind':'latency','group_id':'g','target_tokens':256,'repeat_index':0,
       'transport':{'status':200,'done':True,'error':None,'headers_ms':3,'first_generated_ms':4,'first_content_ms':5,
                    'last_generated_ms':9,'total_ms':12,'final_usage':{'prompt_tokens':10,'completion_tokens':256,
                    'prompt_tokens_details':{'cached_tokens':2}},'events':[event(1,'hello'),event(2,'there')]}}
    d.update(kw); return d


class AnalysisTests(unittest.TestCase):
    def test_nested_raw_sse_and_independent_timing(self):
        r=rec(); out=analysis.summarize([r]); s=next(iter(out['strata'].values()))
        self.assertEqual(s['time_ms']['first_content_ms']['n'],1)
        self.assertEqual(s['time_ms']['first_content_ms']['mean'],5)
        self.assertEqual(s['chunk_speed']['n'],1)
        self.assertEqual(s['usage']['cache_known_requests'],1)

    def test_cluster_bootstrap_deterministic_and_group_gate(self):
        rows=[rec(group_id=f'g{i}',transport={**rec()['transport'],'total_ms':i}) for i in range(25)]
        a=analysis.summarize(rows); b=analysis.summarize(rows)
        self.assertEqual(a,b)
        t=next(iter(a['strata'].values()))['time_ms']['total_ms']
        self.assertIsNotNone(t['median95_ci'])
        self.assertIsNone(t['p95'])
        many=[rec(group_id=f'g{i}',transport={**rec()['transport'],'total_ms':i}) for i in range(100)]
        self.assertIsNotNone(next(iter(analysis.summarize(many)['strata'].values()))['time_ms']['total_ms']['p95'])

    def test_missing_timing_unknown_phase_and_failed_latency_separation(self):
        missing=rec(transport={'status':200,'done':True,'events':[]})
        failed=rec(transport={**rec()['transport'],'status':500,'done':False,'total_ms':99})
        unknown=rec(phase='planned')
        out=analysis.summarize([missing,failed,unknown,rec(phase=None)])
        self.assertEqual(out['formal_requests'],2)
        s=next(iter(out['strata'].values()))
        self.assertEqual(s['time_ms']['total_ms']['n'],0)
        self.assertEqual(s['time_ms']['first_content_ms']['n'],0)
        self.assertEqual(s['time_ms']['failed_total_ms']['n'],1)

    def test_usage_missing_cache_and_invalid(self):
        r=rec(transport={**rec()['transport'],'final_usage':{'prompt_tokens':100,'completion_tokens':300}})
        s=next(iter(analysis.summarize([r])['strata'].values()))['usage']
        self.assertEqual(s['usage_coverage_per_request'],1)
        self.assertEqual(s['cache_coverage_per_request'],0)
        self.assertIsNone(s['token_weighted_cached_rate'])
        bad=rec(transport={**rec()['transport'],'final_usage':{'prompt_tokens':10,'completion_tokens':2,'prompt_cache_hit_tokens':11}})
        self.assertEqual(analysis._usage(bad)['cached'],None)

    def test_speed_guards_and_reasoning(self):
        self.assertEqual(analysis._speed([rec(transport={**rec()['transport'],'final_usage':{'prompt_tokens':1,'completion_tokens':True}})])['n'],0)
        short=rec(transport={**rec()['transport'],'events':[event(10,'x')]})
        self.assertEqual(analysis._speed([short])['n'],0)
        reasoning=rec(transport={**rec()['transport'],'events':[event(1,'x','thought'),event(2,'y')]})
        self.assertEqual(analysis._speed([reasoning])['n'],0)
        failed=rec(transport={**rec()['transport'],'status':500})
        self.assertEqual(analysis._speed([failed])['n'],0)

    def test_pilot_excluded(self):
        out=analysis.summarize([rec(phase='pilot')]); self.assertEqual(out['formal_requests'],0)
        self.assertEqual(out['excluded_pilot'],1)

if __name__=='__main__': unittest.main()
