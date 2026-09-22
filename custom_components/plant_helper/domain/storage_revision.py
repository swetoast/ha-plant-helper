class StorageConflictError(RuntimeError): pass

def check_plant_revision(current: int, expected: int) -> None:
    if current != expected: raise StorageConflictError("plant_changed")

def next_revisions(store_version: int, plant_revision: int) -> tuple[int,int]:
    if store_version < 0 or plant_revision < 0: raise ValueError("revision")
    return store_version+1, plant_revision+1
