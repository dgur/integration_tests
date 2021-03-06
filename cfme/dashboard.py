# -*- coding: utf-8 -*-
import re

from cached_property import cached_property
from navmazing import NavigateToAttribute
from utils.appliance import Navigatable
from utils.timeutil import parsetime
from utils.appliance.implementations.ui import navigator, CFMENavigateStep, navigate_to
from utils.wait import wait_for

from widgetastic.utils import ParametrizedLocator, ParametrizedString, Parameter
from widgetastic.widget import ParametrizedView, Text, View, Widget, ConditionalSwitchableView
from widgetastic.xpath import quote
from widgetastic_patternfly import Button, Dropdown, Tab
from widgetastic_manageiq import Table

from .base.login import BaseLoggedInPage


# TODO: Move this into widgetastic_patternfly
class Kebab(Widget):
    """The so-called "kebab" widget of Patternfly.

    <http://www.patternfly.org/pattern-library/widgets/#kebabs>

    Args:
        button_id: id of the button tag inside the kebab. If not specified, first kebab available
            will be used

    """
    ROOT = ParametrizedLocator('{@locator}')
    UL = './ul[contains(@class, "dropdown-menu")]'
    BUTTON = './button'
    ITEM = './ul/li/a[normalize-space(.)={}]'
    ITEMS = './ul/li/a'

    def __init__(self, parent, button_id=None, logger=None):
        super(Kebab, self).__init__(parent, logger=logger)
        if button_id is not None:
            self.locator = (
                './/div[contains(@class, "dropdown-kebab-pf") and ./button[@id={}]]'.format(
                    quote(button_id)))
        else:
            self.locator = './/div[contains(@class, "dropdown-kebab-pf") and ./button][1]'

    @property
    def is_opened(self):
        """Returns opened state of the kebab."""
        return self.browser.is_displayed(self.UL)

    @property
    def items(self):
        """Lists all items in the kebab.

        Returns:
            :py:class:`list` of :py:class:`str`
        """
        return [self.browser.text(item) for item in self.browser.elements(self.ITEMS)]

    def open(self):
        """Open the kebab"""
        if not self.is_opened:
            self.browser.click(self.BUTTON)

    def close(self):
        """Close the kebab"""
        if self.is_opened:
            self.browser.click(self.BUTTON)

    def select(self, item, close=True):
        """Select a specific item from the kebab.

        Args:
            item: Item to be selected.
            close: Whether to close the kebab after selection. If the item is a link, you may want
                to set this to ``False``
        """
        try:
            self.open()
            self.browser.click(self.ITEM.format(quote(item)))
        finally:
            if close:
                self.close()


class DashboardView(BaseLoggedInPage):
    """View that represents the Intelligence/Dashboard."""
    reset_button = Button(title="Reset Dashboard Widgets to the defaults")

    def reset_widgets(self, cancel=False):
        """Clicks the reset button to reset widgets and handles the alert."""
        self.browser.click(self.reset_button, ignore_ajax=True)
        self.browser.handle_alert(cancel=cancel, wait=10.0)
        self.browser.plugin.ensure_page_safe()

    add_widget = Dropdown('Add a widget')

    @View.nested
    class zoomed(View):  # noqa
        """Represents the zoomed modal panel"""
        title = Text('.//div[@id="lightbox-panel"]//h2[contains(@class, "card-pf-title")]')
        close = Text('.//div[@id="lightbox-panel"]//a[normalize-space(@title)="Close"]')

    def ensure_zoom_closed(self):
        if self.zoomed.title.is_displayed:
            self.zoomed.close.click()

    @ParametrizedView.nested
    class dashboards(Tab, ParametrizedView):    # noqa
        PARAMETERS = ('title', )
        ALL_LOCATOR = './/ul[contains(@class, "nav-tabs-pf")]/li/a'
        COLUMN_LOCATOR = '//div[@id="col{}"]//h2'

        tab_name = Parameter('title')

        @classmethod
        def all(cls, browser):
            return [(browser.text(e), ) for e in browser.elements(cls.ALL_LOCATOR)]

        def column_widget_names(self, column_index):
            """Returns names of widgets in column specified.

            Args:
                column_index: Position of the column. Numbered from 1!

            Returns:
                :py:class:`list` of :py:class:`str`
            """
            return [
                self.browser.text(e)
                for e
                in self.browser.elements(self.COLUMN_LOCATOR.format(column_index))]

        @ParametrizedView.nested
        class widgets(ParametrizedView):  # noqa
            PARAMETERS = ('title', )
            ALL_LOCATOR = '//div[starts-with(@id, "w_")]//h2[contains(@class, "card-pf-title")]'
            BLANK_SLATE = './/div[contains(@class, "blank-slate-pf")]//h1'
            CHART = './div/div/div[starts-with(@id, "miq_widgetchart_")]'
            RSS = './div/div[contains(@class, "rss_widget")]'
            RSS_TABLE = './div[./div[contains(@class, "rss_widget")]]/div/table'
            TABLE = './div/table|./div/div/table'
            MC = (
                './div/div[contains(@class, "mc")]/*[1]|./div/div[starts-with(@id, "dd_w") '
                'and contains(@id, "_box")]/*[1]')
            ROOT = ParametrizedLocator(
                './/div[starts-with(@id, "w_") and .//h2[contains(@class, "card-pf-title")'
                ' and normalize-space(.)={title|quote}]]')

            title = Text('.//h2[contains(@class, "card-pf-title")]')
            menu = Kebab(button_id=ParametrizedString('btn_{@widget_id}'))

            contents = ConditionalSwitchableView(reference='content_type')

            # Unsupported reading yet
            contents.register(None, default=True, widget=Widget())
            contents.register('chart', widget=Widget())

            # Reading supported
            contents.register('table', widget=Table(TABLE))
            contents.register('rss', widget=Table(RSS_TABLE))

            footer = Text('.//div[contains(@class, "card-pf-footer")]')

            @property
            def column(self):
                """Returns the column position of this widget. Numbered from 1!"""
                parent = self.browser.element('..')
                try:
                    parent_id = self.browser.get_attribute('id', parent).strip()
                    return int(re.sub(r'^col(\d+)$', '\\1', parent_id))
                except (ValueError, TypeError, AttributeError):
                    raise ValueError('Could not get the column index of widget')

            @property
            def minimized(self):
                return not self.browser.is_displayed(self.MC)

            @cached_property
            def widget_id(self):
                id_attr = self.browser.get_attribute('id', self)
                return int(id_attr.rsplit('_', 1)[-1])

            @cached_property
            def content_type(self):
                if self.browser.elements(self.BLANK_SLATE):
                    # No data yet
                    return None
                elif self.browser.elements(self.RSS):
                    return 'rss'
                elif self.browser.is_displayed(self.CHART):
                    return 'chart'
                elif self.browser.is_displayed(self.TABLE):
                    return 'table'
                else:
                    return None

            @property
            def blank(self):
                return bool(self.browser.elements(self.BLANK_SLATE))

            @classmethod
            def all(cls, browser):
                return [(browser.text(e), ) for e in browser.elements(cls.ALL_LOCATOR)]

    @property
    def is_displayed(self):
        return (
            self.logged_in_as_current_user and
            self.navigation.currently_selected == ['Cloud Intel', 'Dashboard'])


class ParticularDashboardView(DashboardView):
    @property
    def is_displayed(self):
        return (
            super(ParticularDashboardView, self).is_displayed and
            self.dashboards(title=self.obj.name).is_active)


class DashboardCollection(Navigatable):
    """Represents the Dashboard page and can jump around various dashboards present."""
    @property
    def default(self):
        """Returns an instance of the ``Default Dashboard``"""
        return self.instantiate('Default Dashboard')

    def instantiate(self, name):
        return Dashboard(name, collection=self)

    def all(self):
        view = navigate_to(self.appliance.server, 'Dashboard')
        result = []
        # TODO: Idiomatize the following line
        for (dashboard_name, ) in view.dashboards.view_class.all(view.browser):
            result.append(self.instantiate(dashboard_name))
        return result

    def refresh(self):
        """Refreshes the dashboard view by forcibly clicking the navigation again."""
        view = navigate_to(self.appliance.server, 'Dashboard')
        view.navigation.select('Cloud Intel', 'Dashboard')

    @property
    def zoomed_name(self):
        """Grabs the name of the currently zoomed widget."""
        view = navigate_to(self.appliance.server, 'Dashboard')
        if not view.zoomed.is_displayed:
            return None
        return view.zoomed.title.text

    def close_zoom(self):
        """Closes any zoomed widget."""
        navigate_to(self.appliance.server, 'Dashboard').ensure_zoom_closed()


class Dashboard(Navigatable):
    def __init__(self, name, collection=None, appliance=None):
        if collection is None:
            collection = DashboardCollection(appliance=appliance)
        self.collection = collection
        Navigatable.__init__(self, appliance=collection.appliance)
        self.name = name

    @property
    def dashboard_view(self):
        """Returns a view pointed at a particular dashboard."""
        return navigate_to(self, 'Details').dashboards(title=self.name)

    @cached_property
    def widgets(self):
        return DashboardWidgetCollection(self)

    def drag_and_drop(self, dragged_widget_or_name, dropped_widget_or_name):
        """Drags and drops widgets onto each other."""
        if isinstance(dragged_widget_or_name, DashboardWidget):
            dragged_widget_or_name = dragged_widget_or_name.name
        if isinstance(dropped_widget_or_name, DashboardWidget):
            dropped_widget_object = dropped_widget_or_name
            dropped_widget_or_name = dropped_widget_or_name.name
        else:
            dropped_widget_object = self.widgets.instantiate(dropped_widget_or_name)
        view = self.dashboard_view
        first_widget = view.widgets(title=dragged_widget_or_name).title
        if dropped_widget_object.last_in_column:
            # Different behaviour
            dropped_widget = view.widgets(title=dropped_widget_or_name)
            middle = view.browser.middle_of(dropped_widget)
            position = view.browser.location_of(dropped_widget)
            size = view.browser.size_of(dropped_widget)

            drop_x = middle.x
            drop_y = position.x + size.height + 10
            view.browser.drag_and_drop_to(first_widget, to_x=drop_x, to_y=drop_y)
        else:
            second_widget = view.widgets(title=dropped_widget_or_name).footer
            view.browser.drag_and_drop(first_widget, second_widget)
        view.browser.plugin.ensure_page_safe()


@navigator.register(Dashboard, 'Details')
class DashboardDetails(CFMENavigateStep):
    VIEW = ParticularDashboardView
    prerequisite = NavigateToAttribute('appliance.server', 'Dashboard')

    def step(self):
        self.prerequisite_view.dashboards(title=self.obj.name).select()


class DashboardWidgetCollection(Navigatable):
    def __init__(self, dashboard):
        super(DashboardWidgetCollection, self).__init__(appliance=dashboard.appliance)
        self.dashboard = dashboard

    @property
    def dashboard_view(self):
        return self.dashboard.dashboard_view

    def instantiate(self, name):
        return DashboardWidget(name, self)

    def all(self, content_type=None):  # widgets
        view = self.dashboard_view
        result = []
        # TODO: Idiomatize the following line
        for (widget_name, ) in view.widgets.view_class.all(view.browser):
            w = self.instantiate(widget_name)
            if content_type is None or w.content_type == content_type:
                result.append(self.instantiate(widget_name))
        return result

    def reset(self, cancel=False):
        """Clicks the Reset widgets button."""
        navigate_to(self.dashboard, 'Details').reset_widgets()


class DashboardWidget(Navigatable):
    """Represents a single UI dashboard widget.

    Args:
        name: Name of the widget as displayed in the title.
        widget_collection: The widget collection linked to a dashboard
    """
    def __init__(self, name, widget_collection):
        self.collection = widget_collection
        Navigatable.__init__(self, appliance=widget_collection.appliance)
        self.name = name

    @property
    def dashboard(self):
        return self.collection.dashboard

    @property
    def widget_view(self):
        """Returns a view of the particular widget."""
        return self.dashboard.dashboard_view.widgets(title=self.name)

    @property
    def last_in_column(self):
        """Returns whether this widget is the last in its column"""
        try:
            return (
                self.widget_view.parent.column_widget_names(self.widget_view.column)[-1] ==
                self.name)
        except IndexError:
            return False

    @property
    def footer(self):
        """Return parsed footer value"""
        self.close_zoom()
        cleaned = [
            x.strip()
            for x
            in self.widget_view.footer.text.encode("utf-8").strip().split("|")
        ]
        result = {}
        for item in cleaned:
            name, time = item.split(" ", 1)
            time = time.strip()
            if time.lower() == "never":
                result[name.strip().lower()] = None
            else:
                try:
                    result[name.strip().lower()] = parsetime.from_american_minutes(time.strip())
                except ValueError:
                    result[name.strip().lower()] = parsetime.from_long_date_format(time.strip())
        return result

    @property
    def time_updated(self):
        """Returns a datetime when the widget was last updated."""
        return self.footer["updated"]

    @property
    def time_next(self):
        """Returns a datetime when the widget will be updated."""
        return self.footer["next"]

    @property
    def minimized(self):
        """Returns whether the widget is minimized or not."""
        self.close_zoom()
        return self.widget_view.minimized

    @property
    def blank(self):
        """Returns whether the widget has not been generated before."""
        self.close_zoom()
        return self.widget_view.blank

    @property
    def content_type(self):
        """Returns the type of content of this widget"""
        self.close_zoom()
        return self.widget_view.content_type

    @property
    def contents(self):
        """Returns the WT widget with contents of this dashboard widget."""
        self.close_zoom()
        return self.widget_view.contents

    def minimize(self):
        """Minimize this widget."""
        self.close_zoom()
        view = self.widget_view
        if 'Maximize' not in view.menu.items and 'Minimize' not in view.menu.items:
            raise ValueError('The widget {} cannot be maximized or minimized'.format(self.name))
        if 'Minimize' in view.menu.items:
            view.menu.select('Minimize')

    def restore(self):
        """Maximize this widget."""
        self.close_zoom()
        view = self.widget_view
        view.parent.parent.ensure_zoom_closed()
        if 'Maximize' not in view.menu.items and 'Minimize' not in view.menu.items:
            raise ValueError('The widget {} cannot be maximized or minimized'.format(self.name))
        if 'Maximize' in view.menu.items:
            view.menu.select('Maximize')

    def remove(self):
        """Remove this widget."""
        self.close_zoom()
        view = self.widget_view
        view.menu.select('Remove Widget')

    @property
    def is_zoomed(self):
        """Returns whether this widget is zoomed now."""
        view = self.create_view(DashboardView)
        return view.zoomed.title.is_displayed and view.zoomed.title == self.name

    def zoom(self):
        """Zoom this widget in."""
        if not self.is_zoomed:
            self.close_zoom()
            view = self.widget_view
            view.menu.select('Zoom in', close=False)
            wait_for(lambda: self.is_zoomed, delay=0.2, timeout=10)

    @property
    def can_zoom(self):
        """Returns whether this widget can be zoomed."""
        self.close_zoom()
        view = self.widget_view
        return 'Zoom in' in view.menu.items

    def close_zoom(self):
        """Close zoom. Works theoretically for any widget, it is just exposed here."""
        view = self.create_view(DashboardView)
        if view.is_displayed:
            view.ensure_zoom_closed()
