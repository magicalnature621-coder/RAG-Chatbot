"""Offline tests for HTML scraping and Faculty extraction."""
from backend.crawler.dynamic_pages import extract_faculty, has_unrendered_placeholders
from backend.crawler.scraper import parse_html
from backend.rag.structured import faculty_context_document

CARD = """
<div class="col s12 m6 flex ng-scope" ng-repeat="faculty in faculties = ( facultyCtrl.faculties | filter:facultyCtrl.searchText )">
  <div class="custom-card-header"><h5 class="white-text ng-binding">{name}</h5></div>
  <div class="custom-card-sub-head ng-binding" style="font-weight: bold;"> Head of Department <br> CSE </div>
  <div class="custom-card-sub-head ng-binding"> Assistant Professor </div>
  <ul><li ng-repeat="area in faculty.area" class="ng-binding">{area}</li></ul>
  <div class="custom-card-sub-head"><b class="ng-binding"> PhD from IIT Madras </b></div>
  <div ng-show="faculty.contact.phone" class="chip ng-binding"><i class="material-icons notranslate">contact_phone</i> 0482-2202100 </div>
  <div ng-show="faculty.contact.room" class="chip ng-binding"><i class="material-icons notranslate">location_on</i> Room No: AC 101 <!--room number--></div>
  <div ng-show="faculty.contact.email" class="chip ng-binding"><i class="material-icons notranslate">email</i> {user} at iiitkottayam dot ac.in </div>
  <div ng-show="faculty.contact.phone" class="chip ng-hide"><i class="material-icons">link</i> hidden </div>
</div><!-- end ngRepeat: faculty in faculties = ( facultyCtrl.faculties | filter:facultyCtrl.searchText ) -->
"""


def _page(*cards):
    return "<html><head><meta charset='utf-8'><link rel='stylesheet' href='x.css'></head><body>" + "".join(cards) + "</body></html>"


def test_scraper_keeps_text_after_void_head_tags():
    text = parse_html(_page("<p>Highest CTC 60 LPA</p>"), "https://x")["text"]
    assert "Highest CTC 60 LPA" in text


def test_icon_names_are_not_placeholders():
    assert not has_unrendered_placeholders("contact_phone 0482-2202100 location_on Room AC 101")
    assert has_unrendered_placeholders("{{faculty.name}}")


def test_extract_faculty_from_cards():
    html = _page(CARD.format(name="Dr. Jane Doe", area="Machine Learning", user="jane"),
                 CARD.format(name="Dr. John Roe", area="Cryptography", user="john"))
    records = extract_faculty(html)
    assert [r["name"] for r in records] == ["Dr. Jane Doe", "Dr. John Roe"]
    jane = records[0]
    assert jane["email"] == "jane@iiitkottayam.ac.in"
    assert jane["phone"] == "0482-2202100"
    assert jane["room"] == "AC 101"
    assert jane["designation"] == "Head of Department / CSE / Assistant Professor"
    assert jane["qualification"] == "PhD from IIT Madras"
    assert jane["areas"] == "Machine Learning"


def test_faculty_context_is_filtered_by_question():
    records = [
        {"name": "Dr. Jane Doe", "designation": "Assistant Professor", "areas": "Machine Learning", "email": "j@x"},
        {"name": "Dr. John Roe", "designation": "Professor", "areas": "Cryptography", "email": "r@x"},
    ]
    focused = faculty_context_document(records, "Who works on cryptography?")
    assert "John Roe" in focused and "Jane Doe" not in focused
    assert "Research areas: Cryptography" in focused

    full = faculty_context_document(records, "list all faculty")
    assert "Jane Doe" in full and "John Roe" in full
