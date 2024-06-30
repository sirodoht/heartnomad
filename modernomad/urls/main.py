import django.views
from django.conf import settings
from django.contrib import admin
from django.urls import include, re_path
from django.views.generic import RedirectView

import gather.views
import core.urls.location
import modernomad.views

admin.autodiscover()

urlpatterns = [
    re_path(r"^$", modernomad.views.index),
    re_path(r"^about/$", modernomad.views.about),
    re_path(r"^membership/$", modernomad.views.membership, name="membership"),
    re_path(r"^host/$", modernomad.views.host, name="host"),
    re_path(r"^stay/$", modernomad.views.stay),
    re_path(r"^404/$", modernomad.views.ErrorView),
    re_path(r"^admin/", admin.site.urls),
    re_path(r"^people/", include("modernomad.urls.user")),
    re_path(r"^locations/", include("core.urls.location")),
    re_path(r"^events/$", gather.views.upcoming_events_all_locations),
    re_path(
        r"^events/emailpreferences/(?P<username>[\w\d\-\.@+_]+)/$",
        gather.views.email_preferences,
        name="gather_email_preferences",
    ),
    re_path(r"^accounts/", include("bank.urls")),
    re_path(r"^drft/$", modernomad.views.drft),
    # various other useful things
    re_path(
        r"^favicon\.ico$",
        RedirectView.as_view(url="/static/img/favicon.ico", permanent=True),
    ),
    re_path(r"^robots\.txt$", modernomad.views.robots),
    # api things
    re_path(r"^api/", include("api.urls")),
    re_path(r"^", include("graphapi.urls")),
]

# set media url
media_url = settings.MEDIA_URL.lstrip("/").rstrip("/")
urlpatterns += [
    re_path(
        r"^%s/(?P<path>.*)$" % media_url,  # noqa: UP031
        django.views.static.serve,
        {"document_root": settings.MEDIA_ROOT, "show_indexes": True},
    ),
]
