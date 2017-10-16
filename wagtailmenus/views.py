from __future__ import absolute_import, unicode_literals

import warnings
from copy import copy

from django import forms
from django.contrib.admin.utils import quote, unquote
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.utils.text import capfirst
from django.utils.translation import ugettext as _

from wagtail.wagtailadmin import messages
from wagtail.wagtailadmin.edit_handlers import ObjectList, TabbedInterface
from wagtail.wagtailcore.models import Site

from wagtail.contrib.modeladmin.views import (
    WMABaseView, CreateView, EditView, ModelFormView)

from . import app_settings
from .utils.deprecation import RemovedInWagtailMenus28Warning


class SiteSwitchForm(forms.Form):
    site = forms.ChoiceField(choices=[])

    class Media:
        js = [
            'wagtailmenus/js/site-switcher.js',
        ]

    def __init__(self, current_site, url_helper, **kwargs):
        initial = {'site': url_helper.get_action_url('edit', current_site.pk)}
        super(SiteSwitchForm, self).__init__(initial=initial, **kwargs)
        sites = []
        for site in Site.objects.all():
            sites.append((url_helper.get_action_url('edit', site.pk), site))
        self.fields['site'].choices = sites


class MainMenuIndexView(WMABaseView):

    def dispatch(self, request, *args, **kwargs):
        site = Site.find_for_request(request)
        return redirect(
            self.model_admin.url_helper.get_action_url('edit', site.pk))


class MenuTabbedInterfaceMixin(object):

    def get_edit_handler_class(self):
        if hasattr(self.model, 'edit_handler'):
            edit_handler = self.model.edit_handler
        elif getattr(self.model, 'panels', None):
            warning_msg = (
                "The 'panels' attribute is deprecated for custom menu models. "
                "To customise the admin interface, use the 'content_panels' "
                "and 'settings_panels' attributes to update panels for the "
                "'Content' and 'Settings' tabs independently."
            )
            warnings.warn(warning_msg, RemovedInWagtailMenus28Warning)
            edit_handler = ObjectList(self.model.panels)
        else:
            edit_handler = TabbedInterface([
                ObjectList(self.model.content_panels, heading=_("Content")),
                ObjectList(self.model.settings_panels, heading=_("Settings"),
                           classname="settings"),
            ])
        return edit_handler.bind_to_model(self.model)


class MainMenuEditView(MenuTabbedInterfaceMixin, ModelFormView):
    page_title = _('Editing')
    instance_pk = None
    instance = None

    def __init__(self, model_admin, instance_pk):
        super(MainMenuEditView, self).__init__(model_admin)
        self.instance_pk = unquote(instance_pk)
        self.pk_safe = quote(self.instance_pk)
        self.site = get_object_or_404(Site, id=self.instance_pk)
        self.instance = self.model.get_for_site(self.site)
        self.instance.save()

    @property
    def media(self):
        media = super(MainMenuEditView, self).media
        if self.site_switcher:
            media += self.site_switcher.media
        return media

    @property
    def edit_url(self):
        return self.url_helper.get_action_url('edit', self.instance_pk)

    def get_meta_title(self):
        return _('Editing %(model_name)s') % {
            'model_name': self.opts.verbose_name
        }

    def get_page_subtitle(self):
        return capfirst(self.opts.verbose_name)

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if not self.permission_helper.user_can_edit_obj(user, self.instance):
            raise PermissionDenied
        self.site_switcher = None
        if Site.objects.count() > 1:
            url_helper = self.model_admin.url_helper
            self.site_switcher = SiteSwitchForm(self.site, url_helper)
            site_from_get = request.GET.get('site', None)
            if site_from_get and site_from_get != self.instance_pk:
                return redirect(
                    url_helper.get_action_url('edit', site_from_get))
        return super(MainMenuEditView, self).dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(MainMenuEditView, self).get_context_data(**kwargs)
        context.update({
            'site': self.site,
            'site_switcher': self.site_switcher,
        })
        return context

    def form_valid(self, form):
        form.save()
        messages.success(self.request, _("Main menu updated successfully."))
        return redirect(self.edit_url)

    def get_error_message(self):
        return _("The menu could not be saved due to errors.")

    def get_template_names(self):
        return ['wagtailmenus/mainmenu_edit.html']


class FlatMenuCreateView(MenuTabbedInterfaceMixin, CreateView):
    pass


class FlatMenuEditView(MenuTabbedInterfaceMixin, EditView):
    pass


class FlatMenuCopyView(FlatMenuEditView):
    page_title = _('Copying')

    @property
    def copy_url(self):
        return self.url_helper.get_action_url('copy', self.pk_quoted)

    def get_meta_title(self):
        return _('Copying %(model_name)s') % {
            'model_name': self.opts.verbose_name,
        }

    def check_action_permitted(self, user):
        return self.permission_helper.user_can_create(user)

    def get_form_kwargs(self):
        kwargs = super(FlatMenuCopyView, self).get_form_kwargs()
        """
        When the form is posted, don't pass an instance to the form. It should
        create a new one out of the posted data. We also need to nullify any
        IDs posted for inline menu items, so that new instances of those are
        created too.
        """
        if self.request.method == 'POST':
            data = copy(self.request.POST)
            i = 0
            while(data.get('%s-%s-id' % (
                app_settings.FLAT_MENU_ITEMS_RELATED_NAME, i
            ))):
                data['%s-%s-id' % (
                    app_settings.FLAT_MENU_ITEMS_RELATED_NAME, i
                )] = None
                i += 1
            kwargs.update({
                'data': data,
                'instance': self.model()
            })
        return kwargs

    def get_success_message(self, instance):
        return _("Flat menu '{instance}' created.").format(instance=instance)

    def get_template_names(self):
        return ['wagtailmenus/flatmenu_copy.html']
