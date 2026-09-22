import pytest
from plant_helper_domain.runtime import RuntimeCollection,PlantSetChange

def test_load_add_update_remove_and_generations():
 changes=[]; runtime=RuntimeCollection(); runtime.subscribe(changes.append)
 runtime.load({"a":{"display_name":"A"}})
 assert changes[-1].added==frozenset({"a"}) and runtime.plants["a"].generation==0
 runtime.add("b",{"display_name":"B"})
 assert changes[-1].added==frozenset({"b"})
 plant=runtime.update("a",{"display_name":"A2"})
 assert plant.generation==1 and changes[-1].updated==frozenset({"a"})
 runtime.mark_removing("a"); assert plant.removing and plant.generation==2
 runtime.remove("a"); assert changes[-1].removed==frozenset({"a"}) and "b" in runtime.plants

def test_entity_reverse_index_and_ownership():
 runtime=RuntimeCollection(); runtime.add("a",{}); runtime.add("b",{})
 runtime.bind_entity("sensor.a","a")
 assert runtime.entity_index=={"sensor.a":"a"}
 with pytest.raises(ValueError,match="entity_owned_by_other_plant"): runtime.bind_entity("sensor.a","b")
 runtime.remove("a"); assert runtime.entity_index=={}

def test_listener_unsubscribe_and_unload():
 changes=[]; runtime=RuntimeCollection(); unsub=runtime.subscribe(changes.append)
 unsub(); runtime.add("a",{}); assert changes==[]
 runtime.unload(); assert runtime.unloaded and runtime.plants=={} and runtime.entity_index=={}
 with pytest.raises(RuntimeError,match="runtime_unloaded"): runtime.subscribe(changes.append)

def test_duplicate_missing_guards():
 runtime=RuntimeCollection(); runtime.add("a",{})
 with pytest.raises(ValueError,match="plant_exists"): runtime.add("a",{})
 with pytest.raises(KeyError): runtime.update("missing",{})
 with pytest.raises(KeyError): runtime.remove("missing")
