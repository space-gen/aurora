from scripts.parse_issue_annotation import _parse_issue_body, _parse_regions, circle_to_rle


def test_parse_issue_body_basic():
    body = """
### Task Type
Sunspot

### Record ID
sp-2189

### Your label
class_a,100,100,10

### Confidence score
85%
"""
    fields = _parse_issue_body(body)
    assert fields["task_type"].lower() == "sunspot"
    assert fields["record_id"] == "sp-2189"
    assert "your_label" in fields


def test_parse_regions_circle_to_region():
    regions = _parse_regions("class_a,100,100,10", task_type="sunspot")
    assert len(regions) == 1
    r = regions[0]
    assert r["label"] == "class_a"
    assert "region" in r
    parts = r["region"].split(',')
    assert len(parts) == 3


def test_parse_regions_rle_passthrough_to_region():
    rle_str = "0 10 100 5"
    regions = _parse_regions(f"class_a,{rle_str}", task_type="sunspot")
    assert len(regions) == 1
    assert "region" in regions[0]
    assert regions[0]["region"] == rle_str


def test_circle_to_rle_out_of_bounds():
    # Circle outside the 1024x1024 should return empty string
    rle = circle_to_rle(-100.0, -100.0, 5.0)
    assert rle == ""
