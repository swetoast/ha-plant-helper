import asyncio,copy
from plant_helper_domain.learning import LearningRuntime
from plant_helper_domain.storage import PlantHelperStorage
class B:
 def __init__(self,data=None):self.data=copy.deepcopy(data)
 async def async_load(self):return copy.deepcopy(self.data)
 async def async_save(self,d):self.data=copy.deepcopy(d)
def run(c):return asyncio.run(c)
def setup():
 b=B();s=PlantHelperStorage(b);run(s.async_load());run(s.async_add_plant('a',{'display_name':'A','placement':'indoor'}));l=LearningRuntime(s);run(l.load());return b,s,l
def test_independent_baselines_and_active_buffer():
 b,s,l=setup();run(l.set_baseline('a','indoor',{'complete':True,'mean':44}));run(l.set_baseline('a','outdoor',{'complete':True,'mean':61}));run(l.set_active_samples('a',{'values':[42,43]}))
 assert l.baselines['a']['indoor']['mean']==44 and l.baselines['a']['outdoor']['mean']==61 and l.active_samples['a']['values']==[42,43]
def test_transition_preserves_inactive_baselines_and_clears_only_active_state():
 b,s,l=setup();run(l.set_baseline('a','indoor',{'complete':True,'mean':44}));run(l.set_baseline('a','outdoor',{'complete':True,'mean':61}));run(l.set_active_samples('a',{'values':[42]}));change=run(l.transition('a','outdoor'))
 assert change.changed and change.clear_active_samples and not change.destination_requires_calibration
 assert l.baselines['a']['indoor']['mean']==44 and l.baselines['a']['outdoor']['mean']==61 and l.active_samples['a']=={} and not l.state('a').calibrating
def test_transition_to_incomplete_destination_resumes_calibration():
 b,s,l=setup();run(l.set_baseline('a','indoor',{'complete':True}));change=run(l.transition('a','outdoor'));assert change.destination_requires_calibration and l.state('a').calibrating
 assert l.resume_calibration('a')
def test_species_alias_preserves_learning():
 b,s,l=setup();run(l.set_baseline('a','indoor',{'complete':True,'mean':44}));run(l.set_active_samples('a',{'values':[42]}));change=run(l.species_change('a','Dracaena_trifasciata',' dracaena trifasciata '))
 assert change.kind=='alias' and change.preserve_baselines and l.baselines['a']['indoor']['mean']==44 and l.active_samples['a']['values']==[42]
def test_different_taxon_clears_both_baselines_and_active_buffer():
 b,s,l=setup();run(l.set_baseline('a','indoor',{'complete':True}));run(l.set_baseline('a','outdoor',{'complete':True}));run(l.set_active_samples('a',{'values':[1]}));change=run(l.species_change('a','Dracaena trifasciata','Monstera deliciosa'))
 assert change.kind=='different_taxon' and not change.preserve_baselines and change.clear_active_samples
 assert l.baselines.get('a') is None and l.active_samples['a']=={} and l.state('a').calibrating
def test_persistence_across_restart():
 b,s,l=setup();run(l.set_baseline('a','indoor',{'complete':True,'mean':44}));run(l.set_baseline('a','outdoor',{'complete':False,'values':[60]}));run(l.set_active_samples('a',{'values':[42,43]}))
 s2=PlantHelperStorage(B(b.data));run(s2.async_load());l2=LearningRuntime(s2);run(l2.load())
 assert l2.baselines['a']['indoor']['mean']==44 and l2.baselines['a']['outdoor']['values']==[60] and l2.active_samples['a']['values']==[42,43] and not l2.state('a').calibrating
