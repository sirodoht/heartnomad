from django.contrib.auth import views as auth_views
from django.urls import re_path

from core.views import billing as billing_views
from core.views import user as user_views
from core.views.booking import UserBookings
from core.views.redirects import old_user_bookings_redirect
from gather import views as gather_views

urlpatterns = [
    re_path(r"^$", user_views.ListUsers, name="user_list"),
    re_path(r"^login/$", user_views.user_login, name="user_login"),
    re_path(r"^check/email$", user_views.email_available, name="email_available"),
    re_path(
        r"^check/username$", user_views.username_available, name="username_available"
    ),
    re_path(r"^register/$", user_views.register, name="registration_register"),
    re_path(
        r"^daterange/$", billing_views.PeopleDaterangeQuery, name="people_daterange"
    ),
    re_path(
        r"^(?P<username>(?!logout)(?!login)(?!register)(?!check)[\w\d\-\.@+_]+)/$",
        user_views.UserDetail,
        name="user_detail",
    ),
    re_path(
        r"^(?P<username>[\w\d\-\.@+_]+)/avatar/$",
        user_views.UserAvatar,
        name="user_avatar",
    ),
    re_path(
        r"^(?P<username>[\w\d\-\.@+_]+)/edit/$", user_views.UserEdit, name="user_edit"
    ),
    re_path(
        r"^(?P<username>[\w\d\-\.@+_]+)/create-checkout-session/$",
        billing_views.create_checkout_session,
        name="create_checkout_session",
    ),
    re_path(
        r"^(?P<username>[\w\d\-\.@+_]+)/checkout-success/$",
        billing_views.checkout_success,
        name="checkout_success",
    ),
    re_path(
        r"^(?P<username>[\w\d\-\.@+_]+)/deletecard/$",
        billing_views.user_delete_card,
        name="user_delete_card",
    ),
    re_path(
        r"^(?P<username>[\w\d\-\.@+_]+)/email/$",
        user_views.user_email_settings,
        name="user_email_settings",
    ),
    re_path(
        r"^(?P<username>[\w\d\-\.@+_]+)/events/$",
        user_views.user_events,
        name="user_events",
    ),
    re_path(
        r"^(?P<username>[\w\d\-\.@+_]+)/room/(?P<room_id>\d+)/$",
        user_views.user_edit_room,
        name="user_edit_room",
    ),
    re_path(
        r"^(?P<username>[\w\d\-\.@+_]+)/bookings/$", UserBookings, name="user_bookings"
    ),
    # gracefully handle old urls
    re_path(
        r"^(?P<username>[\w\d\-\.@+_]+)/reservations/$", old_user_bookings_redirect
    ),
    re_path(r"^logout/$", auth_views.LogoutView.as_view(), name="logout"),
    re_path(
        r"^password/reset/$",
        auth_views.PasswordResetView.as_view(),
        name="password_reset",
    ),
    re_path(
        r"^password/done/$",
        auth_views.PasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    re_path(
        r"^password/confirm/(?P<uidb64>[0-9A-Za-z_\-]+)/(?P<token>.+)/$",
        auth_views.PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    re_path(
        r"^password/complete/$",
        auth_views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
]

# XXX can this be extracted and put into the gather app?
# TODO name collision with user_events above.
urlpatterns += (
    re_path(
        r"^(?P<username>[\w\d\-\.@+_]+)/events/$",
        gather_views.user_events,
        name="user_events",
    ),
)
