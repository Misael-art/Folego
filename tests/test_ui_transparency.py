"""Surface alpha must never fade foreground content or fragment label rows."""
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QLabel, QDialog, QCheckBox, QStyle, QStyleOptionButton

from folego.ui import theme, options_tab
from folego.ui.ai_account_panel import AccountPanel
from folego.ui.desktop_shortcuts import VirtualKeyboard
from test_ui_compact import make, snap


@pytest.fixture
def restore_appearance(qapp):
    key, value = theme.TOKENS.key, theme.TOKENS.transparency
    yield
    theme.apply_theme(qapp, key, transparency=value)
    qapp.setProperty('folego_theme_error', '')


@pytest.mark.parametrize('value,alpha', [(0,255),(50,128),(100,0)])
def test_account_surface_alpha_and_opaque_text_without_label_boxes(qapp, restore_appearance, value, alpha):
    theme.apply_theme(qapp, 'snes-us', transparency=value)
    panel = AccountPanel('codex', [])
    panel.resize(560,470);panel.show();qapp.processEvents()
    image = panel.grab().toImage()
    assert abs(image.pixelColor(4,100).alpha()-alpha) <= 1
    assert panel.windowOpacity() == 1
    label = panel.details.findChildren(QLabel)[0]
    origin = label.mapTo(panel, label.rect().topLeft())
    region = image.copy(origin.x(),origin.y(),label.width(),label.height())
    assert max(region.pixelColor(x,y).alpha() for x in range(region.width()) for y in range(region.height())) == 255
    # The empty end of a text row paints no extra layer on the shared backdrop.
    assert abs(region.pixelColor(region.width()-2,2).alpha()-alpha) <= 1


def test_keyboard_and_compact_keep_symbols_at_full_transparency(qapp, restore_appearance):
    theme.apply_theme(qapp, 'ps2', transparency=100)
    view,_ = make(qapp);view.show_snapshot(snap())
    keyboard = VirtualKeyboard(view.shortcut_tabs.controller)
    keyboard.resize(900,260);keyboard.show();qapp.processEvents()
    try:
        image = keyboard.grab().toImage()
        assert image.pixelColor(3,100).alpha() == 0
        key = keyboard.letters[0]
        rect = key.geometry()
        region = image.copy(rect)
        assert max(region.pixelColor(x,y).alpha() for x in range(region.width()) for y in range(region.height())) == 255
        for widget in (keyboard,view):
            assert widget.windowOpacity() == 1
            assert widget.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        assert theme.TOKENS.text in view.detail_label.styleSheet()
        assert 'rgba(' in keyboard.styleSheet()
    finally:
        keyboard.hide();view.force_close()


def test_dialog_background_uses_alpha_without_fading_the_window(qapp,restore_appearance):
    theme.apply_theme(qapp,'ps2',transparency=50)
    dialog=QDialog();dialog.resize(250,120);dialog.show();qapp.processEvents()
    assert abs(dialog.grab().toImage().pixelColor(20,20).alpha()-128)<=1
    assert dialog.windowOpacity()==1


@pytest.mark.parametrize('value,alpha', [(0,255),(50,128),(100,0)])
def test_actual_account_popup_has_one_background_layer(qapp,restore_appearance,value,alpha):
    from PySide6.QtCore import QPoint
    theme.apply_theme(qapp,'ps2',transparency=value)
    view,_=make(qapp)
    try:
        view.ai_strip.details('codex');qapp.processEvents()
        menu=view.ai_strip.account_menu;panel=view.ai_strip.account_panel
        image=menu.grab().toImage();point=panel.mapTo(menu,QPoint(4,100))
        assert abs(image.pixelColor(point).alpha()-alpha)<=1
    finally:view.force_close()


def test_persistence_theme_change_and_invalid_saved_transparency(qapp,tmp_path,restore_appearance):
    store = QSettings(str(tmp_path/'appearance.ini'),QSettings.Format.IniFormat)
    theme.choose_transparency(65,store=store)
    theme.choose_theme('mega-drive',store=store)
    assert theme.TOKENS.transparency == 65
    theme.apply_theme(qapp,'pc-engine',transparency=0)
    theme.apply_theme(qapp,store=store)
    assert theme.TOKENS.key == 'mega-drive' and theme.TOKENS.transparency == 65
    store.setValue(theme.TRANSPARENCY_KEY,'broken');store.sync()
    theme.apply_theme(qapp,store=store)
    assert theme.TOKENS.transparency == 0
    assert 'Transparência salva desconhecida' in qapp.property('folego_theme_error')
    assert store.value(theme.TRANSPARENCY_KEY) == 'broken'
    for invalid in (True,-1,101,12.5,'50'):
        with pytest.raises(ValueError): theme.choose_transparency(invalid,store=store)
    assert theme.TOKENS.transparency == 0


def test_slider_previews_without_writes_saves_on_release_and_rolls_back_failure(qapp,monkeypatch,tmp_path,restore_appearance):
    class Jobs:
        def shutdown(self): pass
    theme.apply_theme(qapp,'ps2',transparency=0)
    store=QSettings(str(tmp_path/'appearance.ini'),QSettings.Format.IniFormat)
    writes=[]
    def save(value):
        writes.append(value);theme.choose_transparency(value,store=store)
    monkeypatch.setattr(options_tab,'choose_transparency',save)
    first=options_tab.OptionsTab(jobs=Jobs());second=options_tab.OptionsTab(jobs=Jobs())
    slider=first.background_slider
    slider.setSliderDown(True)
    slider.setValue(20);slider.setValue(70)
    assert not writes and theme.TOKENS.transparency == 70
    assert second.background_slider.value() == 70
    slider.setSliderDown(False)
    assert writes == [70] and store.value(theme.TRANSPARENCY_KEY) == 70
    def fail(value): raise RuntimeError('Não foi salvo')
    monkeypatch.setattr(options_tab,'choose_transparency',fail)
    slider.setSliderDown(True);slider.setValue(95);slider.setSliderDown(False)
    assert theme.TOKENS.transparency == 70
    assert slider.value() == second.background_slider.value() == 70
    assert 'Não foi salvo' in first.theme_status.text()
    # Keyboard/accessibility changes also persist without requiring a drag.
    monkeypatch.setattr(options_tab,'choose_transparency',save)
    slider.setValue(40)
    assert writes == [70,40]


def test_failed_save_does_not_change_appearance(qapp,restore_appearance):
    class ReadOnly:
        def setValue(self,*args): pass
        def sync(self): pass
        def status(self): return QSettings.Status.AccessError
    theme.apply_theme(qapp,'ps2',transparency=35)
    with pytest.raises(RuntimeError): theme.choose_transparency(90,store=ReadOnly())
    assert theme.TOKENS.transparency == 35


@pytest.mark.parametrize('value', [0,100])
def test_checkbox_states_stay_visible_and_distinct(qapp,restore_appearance,value):
    theme.apply_theme(qapp,'ps2',transparency=value)
    control=QCheckBox('Marcação');control.resize(180,35);control.show();qapp.processEvents()
    images=[]
    for checked in (False,True):
        control.setChecked(checked);qapp.processEvents()
        option=QStyleOptionButton();control.initStyleOption(option)
        rect=control.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator,option,control)
        image=control.grab().toImage().copy(rect)
        assert max(image.pixelColor(x,y).alpha() for x in range(image.width()) for y in range(image.height()))==255
        images.append(bytes(image.constBits()))
    assert images[0]!=images[1]
