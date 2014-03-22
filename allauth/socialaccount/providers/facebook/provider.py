import json

from django.core.urlresolvers import reverse
from django.core.exceptions import ImproperlyConfigured
from django.template.loader import render_to_string
from django.template import RequestContext
from django.utils.html import mark_safe
from django.utils.crypto import get_random_string

from allauth.utils import import_callable
from allauth.account.models import EmailAddress
from allauth.socialaccount import providers
from allauth.socialaccount.providers.base import (ProviderAccount,
                                                  AuthProcess,
                                                  AuthAction)
from allauth.socialaccount.providers.oauth2.provider import OAuth2Provider
from allauth.socialaccount.app_settings import QUERY_EMAIL
from allauth.socialaccount.models import SocialApp

from .locale import get_default_locale_callable


NONCE_SESSION_KEY = 'allauth_facebook_nonce'
NONCE_LENGTH = 32


class FacebookAccount(ProviderAccount):
    def get_profile_url(self):
        return self.account.extra_data.get('link')

    def get_avatar_url(self):
        uid = self.account.uid
        return 'https://graph.facebook.com/%s/picture?type=large&return_ssl_resources=1' % uid  # noqa

    def to_str(self):
        dflt = super(FacebookAccount, self).to_str()
        return self.account.extra_data.get('name', dflt)


class FacebookProvider(OAuth2Provider):
    id = 'facebook'
    name = 'Facebook'
    package = 'allauth.socialaccount.providers.facebook'
    account_class = FacebookAccount

    def __init__(self):
        self._locale_callable_cache = None
        super(FacebookProvider, self).__init__()

    def get_method(self):
        return self.get_settings().get('METHOD', 'oauth2')

    def get_login_url(self, request, **kwargs):
        method = kwargs.get('method', self.get_method())
        if method == 'js_sdk':
            next = "'%s'" % (kwargs.get('next') or '')
            process = "'%s'" % (kwargs.get('process') or AuthProcess.LOGIN)
            action = "'%s'" % (kwargs.get('action') or AuthAction.AUTHENTICATE)
            ret = "javascript:allauth.facebook.login(%s, %s, %s)" \
                % (next, action, process)
        else:
            assert method == 'oauth2'
            ret = super(FacebookProvider, self).get_login_url(request,
                                                              **kwargs)
        return ret

    def _get_locale_callable(self):
        settings = self.get_settings()
        f = settings.get('LOCALE_FUNC')
        if f:
            f = import_callable(f)
        else:
            f = get_default_locale_callable()
        return f

    def get_locale_for_request(self, request):
        if not self._locale_callable_cache:
            self._locale_callable_cache = self._get_locale_callable()
        return self._locale_callable_cache(request)

    def get_default_scope(self):
        scope = []
        if QUERY_EMAIL:
            scope.append('email')
        return scope

    def get_auth_params(self, request, action):
        ret = super(FacebookProvider, self).get_auth_params(request,
                                                            action)
        if action == AuthAction.REAUTHENTICATE:
            ret['auth_type'] = 'reauthenticate'
        return ret

    def get_fb_login_options(self, request):
        ret = self.get_auth_params(request, 'authenticate')
        ret['scope'] = ','.join(self.get_scope())
        if ret.get('auth_type') == 'reauthenticate':
            ret['auth_nonce'] = self.get_nonce(request, or_create=True)
        return ret

    def media_js(self, request):
        locale = self.get_locale_for_request(request)
        try:
            app = self.get_app(request)
        except SocialApp.DoesNotExist:
            raise ImproperlyConfigured("No Facebook app configured: please"
                                       " add a SocialApp using the Django"
                                       " admin")
        fb_login_options = self.get_fb_login_options(request)
        ctx = {'facebook_app': app,
               'facebook_channel_url':
               request.build_absolute_uri(reverse('facebook_channel')),
               'fb_login_options': mark_safe(json.dumps(fb_login_options)),
               'facebook_jssdk_locale': locale}
        return render_to_string('facebook/fbconnect.html',
                                ctx,
                                RequestContext(request))

    def get_nonce(self, request, or_create=False, pop=False):
        if pop:
            nonce = request.session.pop(NONCE_SESSION_KEY, None)
        else:
            nonce = request.session.get(NONCE_SESSION_KEY)
        if not nonce and or_create:
            nonce = get_random_string(32)
            request.session[NONCE_SESSION_KEY] = nonce
        return nonce

    def extract_uid(self, data):
        return data['id']

    def extract_common_fields(self, data):
        return dict(email=data.get('email'),
                    username=data.get('username'),
                    first_name=data.get('first_name'),
                    last_name=data.get('last_name'))

    def extract_email_addresses(self, data):
        ret = []
        email = data.get('email')
        if email:
            # data['verified'] does not imply the email address is
            # verified.
            ret.append(EmailAddress(email=email,
                                    verified=False,
                                    primary=True))
        return ret

providers.registry.register(FacebookProvider)
