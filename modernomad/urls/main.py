import django.views
from django.conf import settings
from django.contrib import admin
from django.urls import include, re_path
from django.views.generic import RedirectView

from core.views import membership as membership_views
from gather import views as gather_views
from modernomad import views as modernomad_views

admin.autodiscover()

urlpatterns = [
    # Core views
    re_path(r"^$", modernomad_views.index),
    re_path(r"^about/$", modernomad_views.about),
    re_path(r"^host/$", modernomad_views.host, name="host"),
    re_path(r"^stay/$", modernomad_views.stay),
    re_path(r"^404/$", modernomad_views.ErrorView),
    re_path(r"^admin/", admin.site.urls),
    re_path(r"^membership/$", membership_views.manage, name="membership_manage"),
    re_path(
        r"^membership/charge_membership/$",
        membership_views.charge,
        name="membership_charge",
    ),
    re_path(r"^people/", include("modernomad.urls.user")),
    re_path(r"^locations/", include("core.urls.location")),
    re_path(r"^events/$", gather_views.upcoming_events_all_locations),
    re_path(
        r"^events/emailpreferences/(?P<username>[\w\d\-\.@+_]+)/$",
        gather_views.email_preferences,
        name="gather_email_preferences",
    ),
    re_path(r"^accounts/", include("bank.urls")),
    re_path(r"^drft/$", modernomad_views.drft),
    # Utility views
    re_path(
        r"^favicon\.ico$",
        RedirectView.as_view(url="/static/img/favicon.ico", permanent=True),
    ),
    re_path(r"^robots\.txt$", modernomad_views.robots),
    # API
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
