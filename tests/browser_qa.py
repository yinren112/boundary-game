"""Exercise the shipped file in Edge. Requires the existing Python Playwright installation.

python tests/browser_qa.py --out <screenshot-directory>
"""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
args.out.mkdir(parents=True, exist_ok=True)
(args.out / 'results.json').unlink(missing_ok=True)
url = (Path(__file__).resolve().parents[1] / 'index.html').as_uri() + '?qa'


def state(page):
    return page.evaluate('__boundary.state()')


def settle(page):
    page.wait_for_function('() => __boundary.settled()')
    page.wait_for_timeout(35)


def next_point(page):
    return page.evaluate('''() => {
        const s = __boundary.state(), g = __boundary.graph(), edge = g.edges[__boundary.route()[0]];
        const id = edge.a === s.current ? edge.b : edge.a;
        return {id, ...__boundary.project(id)};
    }''')


def reveal(page, target):
    if not target['visible']:
        page.evaluate('(id) => __boundary.focus(id)', target['id'])
        settle(page)
    point = page.evaluate('(id) => __boundary.project(id)', target['id'])
    assert point['visible'], ('target occluded after focus', state(page), target, point)
    assert page.evaluate('(p) => __boundary.pick(p.x, p.y)', point) == target['id'], ('ambiguous pick', target)
    return point


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, channel='msedge')
    context = browser.new_context(viewport={'width':1440, 'height':1000}, reduced_motion='reduce')
    page = context.new_page()
    errors, results = [], []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' else None)
    page.goto(url, wait_until='networkidle')
    assert page.evaluate('window.BOUNDARY_READY')
    page.screenshot(path=str(args.out / 'home.png'))

    page.evaluate('__boundary.loadLevel(9)')
    for target_id in [8,9] * 5:
        page.evaluate('(id) => __boundary.focus(id)',target_id)
        settle(page)
        assert page.evaluate('(id) => __boundary.project(id).visible',target_id), 'half-turn focus failed'

    # Primary-button semantics, undo/redo, and one continuous fast drag.
    page.evaluate('__boundary.loadLevel(1)')
    settle(page)
    points = page.evaluate('__boundary.graph().vertices.map(v => __boundary.project(v.id))')
    assert all(point['visible'] for point in points), 'all five ring vertices must be visible at entry'
    target = reveal(page, next_point(page))
    for button in ['right', 'middle']:
        page.mouse.click(target['x'], target['y'], button=button)
        assert state(page)['used'] == 0, button
    page.mouse.click(target['x'], target['y'])
    assert state(page)['used'] == 1
    page.keyboard.press('z')
    assert state(page)['used'] == 0
    settle(page)
    page.keyboard.press('y')
    assert state(page)['used'] == 1
    page.locator('#undo-button').click()
    settle(page)
    page.locator('#redo-button').click()
    assert state(page)['used'] == 1
    page.keyboard.press('z')
    settle(page)
    page.keyboard.press('Shift+Z')
    assert state(page)['used'] == 1
    page.evaluate('__boundary.loadLevel(1)')
    settle(page)
    origin = page.evaluate('__boundary.project(__boundary.state().current)')
    page.mouse.move(origin['x'], origin['y'])
    page.mouse.down()
    for expected in [1, 2, 3]:
        target = next_point(page)
        page.mouse.move(target['x'], target['y'], steps=2)
        assert state(page)['used'] == expected, 'fast drag skipped a vertex'
    page.mouse.up()
    assert state(page)['used'] == 3

    # Reload restores the exact route through the same file URL and v1 storage.
    old = state(page)
    page.reload(wait_until='networkidle')
    page.locator('[data-action="continue"]').click()
    restored = state(page)
    assert restored['history'] == old['history'] and restored['current'] == old['current']
    page.locator('.game-breadcrumb [data-action="levels"]').click()
    page.locator('[data-action="level"][data-level="1"]').click()
    assert state(page)['history'] == old['history'], 'reselecting the active level erased the route'
    page.keyboard.press('Escape')
    frozen = state(page)['elapsed']
    page.wait_for_timeout(350)
    assert state(page)['elapsed'] == frozen
    page.keyboard.press('Escape')

    # A wheel zoom survives settings rebuilds; reset restores the initial framing.
    page.evaluate('__boundary.loadLevel(1)')
    settle(page)
    def extent():
        return page.evaluate('''() => { const p=__boundary.graph().vertices.map(v=>__boundary.project(v.id)); return Math.max(...p.map(v=>v.x))-Math.min(...p.map(v=>v.x)); }''')
    original_extent = extent()
    stage = page.locator('#stage canvas').bounding_box()
    page.mouse.move(stage['x']+stage['width']/2,stage['y']+stage['height']/2)
    page.mouse.wheel(0,-240)
    page.wait_for_timeout(650)
    enlarged = extent()
    assert enlarged > original_extent * 1.15, 'wheel failed to zoom'
    for theme in ['amber','moon','jade']:
        page.locator('[data-action="settings"]').click()
        page.locator(f'[data-theme="{theme}"][data-action="theme"]').click()
        page.locator('[data-setting="quality"]').select_option('high')
        page.locator('[data-setting="traces"]').set_checked(True)
        page.locator('[data-action="close"]').last.click()
        assert abs(extent() - enlarged) < 1.5, 'setting reset the camera zoom'
        page.screenshot(path=str(args.out / f'theme-{theme}.png'))
    page.keyboard.press('r')
    settle(page)
    page.wait_for_timeout(650)
    assert abs(extent()-original_extent) < 1.5, 'reset failed to restore zoom'
    page.locator('[data-action="settings"]').click()
    page.locator('[data-setting="quality"]').select_option('auto')
    page.locator('[data-setting="traces"]').set_checked(False)
    page.locator('[data-action="close"]').last.click()

    # Every edge in every campaign level is traversed by real pointer clicks.
    for level in range(1, 25):
        page.evaluate('(id) => __boundary.loadLevel(id)', level)
        settle(page)
        page.screenshot(path=str(args.out / f'level-{level:02}.png'))
        total = state(page)['total']
        captured_inner = False
        for expected in range(1, total + 1):
            target = reveal(page, next_point(page))
            page.mouse.click(target['x'], target['y'])
            now = state(page)
            assert now['used'] == expected, ('click did not advance exactly once', level, expected, now)
            assert not now['stranded']
            if len(now['unlocked']) > 1 and not captured_inner:
                page.wait_for_timeout(120)
                page.screenshot(path=str(args.out / f'inner-{level:02}.png'))
                captured_inner = True
        assert state(page)['complete']
        page.wait_for_selector('#dialog[open]')
        results.append({'level':level, 'moves':total, 'complete':True})
        print(f'PASS level {level:02}: {total} pointer moves', flush=True)

    # The visible hint control must orient to a selectable legal continuation.
    page.evaluate('__boundary.loadLevel(11)')
    page.locator('#hint-button').click()
    settle(page)
    target = next_point(page)
    assert target['visible'], 'hint left its target hidden'
    point = reveal(page,target)
    page.mouse.click(point['x'],point['y'])
    assert state(page)['used'] == 1 and state(page)['hints'] == 1
    page.evaluate('__boundary.loadLevel(1)')

    # Exercise the daily and seeded game entry paths and the new-game confirmation.
    for difficulty in [1,2,3]:
        page.locator('.main-nav [data-action="endless"]').click()
        page.locator('#seed-input').fill('boundary-qa')
        page.locator(f'[data-difficulty="{difficulty}"]').click()
        page.locator('[data-action="generate"]').click()
        if page.locator('#dialog[open] [data-action="confirm"]').count():
            page.locator('[data-action="confirm"]').click()
        assert state(page)['config']['difficulty'] == difficulty
        for _ in range(3):
            point = reveal(page,next_point(page))
            page.mouse.click(point['x'],point['y'])
        assert state(page)['used'] == 3
    page.locator('.main-nav [data-action="daily"]').click()
    page.locator('[data-action="confirm"]').click()
    assert state(page)['config']['mode'] == 'daily'
    point = reveal(page,next_point(page))
    page.mouse.click(point['x'],point['y'])
    assert state(page)['used'] == 1
    page.locator('.main-nav [data-action="daily"]').click()
    assert state(page)['used'] == 1, 'daily entry reset today\'s route'

    # Different viewport shapes must keep the initial sculpture inside its canvas.
    for width, height in [(1440,900),(1024,768),(390,844),(320,568),(844,390)]:
        page.set_viewport_size({'width':width,'height':height})
        for level in [1,6,11,21,24]:
            page.evaluate('(id) => __boundary.loadLevel(id)', level)
            settle(page)
            bounds = page.locator('#stage canvas').bounding_box()
            points = page.evaluate('__boundary.graph().vertices.map(v => __boundary.project(v.id))')
            assert all(bounds['x']+5 < v['x'] < bounds['x']+bounds['width']-5 and bounds['y']+5 < v['y'] < bounds['y']+bounds['height']-5 for v in points), ('clipped model',width,height,level)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'horizontal overflow'
        page.screenshot(path=str(args.out / f'viewport-{width}x{height}.png'))
        initial = page.evaluate('__boundary.rotation()')
        page.locator('[data-action="reset-camera"]').focus()
        page.keyboard.press('ArrowLeft')
        assert page.evaluate('__boundary.rotation()') != initial
        page.keyboard.press('r')
        settle(page)
        final = page.evaluate('__boundary.rotation()')
        assert max(abs(a-b) for a,b in zip(initial,final)) < 1e-6, 'reset did not restore initial rotation'

    # Pinching without motion and pointer cancellation must never make a move.
    touch_context = browser.new_context(viewport={'width':390,'height':844}, has_touch=True, is_mobile=True, reduced_motion='reduce')
    touch = touch_context.new_page()
    touch.goto(url,wait_until='networkidle')
    touch.evaluate('__boundary.loadLevel(1)')
    settle(touch)
    target=next_point(touch)
    cdp=touch_context.new_cdp_session(touch)
    cdp.send('Input.dispatchTouchEvent', {'type':'touchStart','touchPoints':[{'x':target['x'],'y':target['y'],'id':0},{'x':target['x']+35,'y':target['y']+30,'id':1}]})
    cdp.send('Input.dispatchTouchEvent', {'type':'touchEnd','touchPoints':[]})
    assert state(touch)['used'] == 0, 'two-finger contact advanced the path'
    cdp.send('Input.dispatchTouchEvent', {'type':'touchStart','touchPoints':[{'x':target['x'],'y':target['y'],'id':0}]})
    cdp.send('Input.dispatchTouchEvent', {'type':'touchCancel','touchPoints':[]})
    assert state(touch)['used'] == 0, 'cancel advanced the path'
    touch.touchscreen.tap(target['x'],target['y'])
    assert state(touch)['used'] == 1, 'touch tap did not advance'
    before_pinch = touch.evaluate('__boundary.project(0)')
    cdp.send('Input.dispatchTouchEvent', {'type':'touchStart','touchPoints':[{'x':130,'y':400,'id':0},{'x':230,'y':400,'id':1}]})
    cdp.send('Input.dispatchTouchEvent', {'type':'touchMove','touchPoints':[{'x':90,'y':400,'id':0},{'x':270,'y':400,'id':1}]})
    cdp.send('Input.dispatchTouchEvent', {'type':'touchEnd','touchPoints':[]})
    touch.wait_for_timeout(600)
    after_pinch = touch.evaluate('__boundary.project(0)')
    assert abs(before_pinch['x']-after_pinch['x']) > 5, 'pinch did not change the view'
    assert state(touch)['used'] == 1, 'pinch moved the path'
    assert not errors, errors
    (args.out / 'results.json').write_text(json.dumps({'errors':errors, 'levels':results, 'viewports':5, 'touch':True},indent=2),encoding='utf-8')
    browser.close()
    print(f'PASS: {len(results)} campaign completions; input, save, pause, framing, touch; no browser errors')
