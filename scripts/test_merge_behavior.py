from runpy import run_path
import json

# Load the merge module into a namespace
ns = run_path('scripts/merge_annotations_to_hf.py', run_name='merge_mod')
_merge = ns.get('_merge_annotations_list')

remote = json.dumps([
    {
        "user": "alice",
        "issue_number": 1,
        "timestamp": "2026-01-01T00:00:00Z",
        "locations": [{"label": "class_f", "rle": "100 10"}]
    }
])

local = [
    {
        "user": "alice",
        "issue_number": 2,
        "timestamp": "2026-01-02T00:00:00Z",
        "locations": [{"label": "class_f", "region": "100 10"}]
    },
    {
        "user": "bob",
        "issue_number": 3,
        "timestamp": "2026-01-03T00:00:00Z",
        "locations": [{"label": "class_a", "region": "200 5"}]
    }
]

out = _merge(remote, local)
print(out)
