"""Synthetic NCL OPEN LAB pages generated from the room configuration.

IMPORTANT: these are SYNTHETIC fixtures modelled on the DOM that was observed
live and recorded in docs/ncl_openlab_probe.md. They prove the engine's
selection logic offline. They are NOT proof that the live site still behaves
this way, and they never replace a live check.

A new room added to ncl_openlab_rooms.json automatically gets a page here.
"""
import html as _html
import re

NCL_URL_GRID = "https://spms.ncl.edu.tw/NLT/co/media_discussion.jsp"
NCL_URL_STATUS = "https://spms.ncl.edu.tw/NLT/co/multimedia.jsp"

# Decoys are neighbours that a sloppy matcher would click by mistake.
DECOY_TILES = ("P13 個人直播室", "P030 個人直播室")
DECOY_STATUS = ("討論室", "多媒體討論")

_SCRIPT = r"""
const mark = %(mark)s;
const sel = (selector, cls) => {
  document.querySelectorAll(selector).forEach(el => el.addEventListener('click', () => {
    if (el.classList.contains('disabled')) return;
    document.querySelectorAll(selector).forEach(x => x.classList.remove(cls));
    el.classList.add(cls);
  }));
};
sel('.date-box', 'selected');
sel('.space-box1', 'selected');
sel('.%(slot_class)s[data-param1]', mark);
document.querySelector('.next-btn') && document.querySelector('.next-btn').addEventListener('click', () => {
  const chosen = document.querySelector('.%(slot_class)s.' + mark);
  window.__slot = chosen ? chosen.getAttribute('data-param1') : '';
  document.body.innerHTML = %(checkout)s.replaceAll('__SLOT__', window.__slot);
  const go = document.getElementById('gobook');
  if (go) go.addEventListener('click', () => {
    window.__booked = (window.__booked || 0) + 1;
    document.body.innerHTML = %(result)s.replaceAll('__SLOT__', window.__slot);
  });
});
"""


def _js(value):
    import json
    return json.dumps(value, ensure_ascii=False)


def near_miss_label(label):
    """A different room that reads almost the same: next code number, or last char swapped."""
    match = re.search(r"\d", label)
    if match is None:
        return label[:-1] + "X"
    digit = label[match.start()]
    return label[:match.start()] + str((int(digit) + 1) % 10) + label[match.start() + 1:]


def longer_code_label(label):
    """'縫紉機01' -> '縫紉機010': same prefix, different (longer) code. Same text if no digit."""
    matches = list(re.finditer(r"\d+", label))
    return label if not matches else label[:matches[0].end()] + "0" + label[matches[0].end():]


def grid_html(registry, room_key, day, *, decoys=True, dup_room=False,
              room_disabled=False, date_disabled=False, date_missing=False,
              slot_state="enabled", checkout="ok", result="success",
              next_button=True, site=None):
    """``site`` pins the simulated website behaviour independent of the config.

    Keys: slot_class, requires_book, mark. When omitted the behaviour is
    derived from the room's flow (fine for matrix tests; parity tests pin it to
    the live-observed values so a config mistake cannot hide itself).
    """
    profile = registry.room(room_key)
    flow = profile.flow
    site = site or {
        "slot_class": flow.slot_selector[1:].split("[")[0],
        "requires_book": flow.slot_requires_book_class,
        "mark": "book" if flow.book_class_marks_selected else "selected"}
    slot_class = site["slot_class"]
    short, full, iso = day.strftime("%m/%d"), day.strftime("%Y/%m/%d"), day.isoformat()
    esc = _html.escape

    dates = [] if date_missing else [
        f'<div class="date-box{" disabled" if date_disabled else ""}" id="d0">'
        f'{short}<br><span class="weekWords">(三,Wed)</span></div>']
    dates.append('<div class="date-box" id="d1">99/99<br><span class="weekWords">(x)</span></div>')

    rooms = [f'<div class="space-box1{" disabled" if room_disabled else ""}">'
             f'{esc(p.sample_tile_label)}</div>' for p in registry.rooms.values()]
    if dup_room:
        rooms.append(f'<div class="space-box1">{esc(profile.sample_tile_label)}</div>')
    if decoys:
        rooms.extend(f'<div class="space-box1">{esc(t)}</div>' for t in DECOY_TILES)

    slots = []
    for slot in profile.slots:
        classes = [slot_class]
        if site["requires_book"] and slot_state != "no_book":
            classes.append("book")
        if slot_state == "disabled":
            classes.extend(["disabled", "reserving"])
        slots.append(f'<div class="{" ".join(classes)}" data-param1="{slot}">{slot}</div>')

    summary = profile.sample_tile_label
    shown_summary = {"wrong_room": "P99 其他空間",
                     "near_miss_room": near_miss_label(summary),
                     "longer_code_room": longer_code_label(summary)}.get(checkout, summary)
    gobook_date = "2000-01-01" if checkout == "wrong_date_attr" else iso
    gobook_slot = "00:00-00:01" if checkout == "wrong_slot_attr" else "__SLOT__"
    button = ""
    if checkout != "missing_button":
        button = (f'<button id="gobook" class="submit-circle-button" '
                  f'data-param2="{gobook_date}" data-param5="{gobook_slot}">預 約</button>')
        if checkout == "duplicate_button":
            button += button
    overlay = ('<div style="position:fixed;left:0;top:0;width:100%;height:100%;'
               'z-index:99999;background:rgba(0,0,0,.1)"></div>'
               if checkout == "occluded" else "")
    checkout_html = (f"<div>預約確認 {full} {esc(shown_summary)} __SLOT__</div>"
                     f"{button}{overlay}")
    result_html = {
        "success": f"<div>預約成功 {full} {esc(summary)} __SLOT__</div>",
        "failure": "<div>預約失敗</div>",
        "ambiguous": "<div>處理中</div>",
        "wrong_slot": f"<div>預約成功 {full} {esc(summary)} 00:00-00:01</div>",
    }[result]

    script = _SCRIPT % {
        "mark": _js(site["mark"]),
        "slot_class": slot_class,
        "checkout": _js(checkout_html),
        "result": _js(result_html),
    }
    nxt = '<a class="next-btn" href="#">下 一 步</a>' if next_button else ""
    return ("<!doctype html><meta charset='utf-8'><body>"
            f"<div id='dates'>{''.join(dates)}</div>"
            f"<div id='spaces'>{''.join(rooms)}</div>"
            f"<div id='times'>{''.join(slots)}</div>{nxt}"
            f"<script>{script}</script></body>")


def status_html(registry, *, dup_label=None):
    # entry_label is a CATEGORY on the status page; several rooms may share one.
    # Rooms with entry_label None have no known category and are opened by hand.
    labels = list(dict.fromkeys(p.entry_label for p in registry.rooms.values()
                                if p.entry_label is not None))
    labels.extend(DECOY_STATUS)
    if dup_label:
        labels.append(dup_label)
    items = "".join(
        f'<div class="lab-item"><span class="lab-name" data-zh="{_html.escape(l)}">'
        f'{_html.escape(l)}</span></div>' for l in labels)
    return ("<!doctype html><meta charset='utf-8'><body>" + items +
            "<script>window.__opened = null;"
            "document.querySelectorAll('.lab-item').forEach(el => el.addEventListener("
            "'click', () => { window.__opened = el.querySelector('.lab-name')"
            ".getAttribute('data-zh'); }));</script></body>")


def step(js):
    return {"js": js}


FULL_WALK_CODES = ["CLICKED", "CLICKED", "CLICKED", "CLICKED",
                   "READY_FOR_POINTER_CLICK", "CLICKED_PAGE", "SUCCESS_PAGE_MATCHED"]


def walk_steps(action_script, day, slot, mode, *, through="success"):
    """date -> room -> slot -> next -> submit(ready) -> real pointer click -> success."""
    order = ["date", "room", "slot", "next", "submit"]
    steps = [step(action_script(phase, day, slot, mode)) for phase in order]
    if through == "submit":
        return steps
    steps.append({"click_prev_xy": True})
    steps.append(step(action_script("success", day, slot, mode)))
    return steps
