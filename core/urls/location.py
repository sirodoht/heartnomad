from django.urls import include, re_path

from core.emails import messages
from core.views import booking, location, occupancy, redirects

per_location_patterns = [
    re_path(r"^$", location.LocationDetail.as_view(), name="location_detail"),
    re_path(r"^stay/$", booking.StayView.as_view(), name="location_stay"),
    re_path(r"^stay/room/(?P<room_id>\w+)$", booking.StayView.as_view(), name="room"),
    re_path(r"^community/$", location.community, name="location_community"),
    re_path(r"^team/$", location.team, name="location_team"),
    re_path(r"^guests/$", location.guests, name="location_guests"),
    re_path(r"^occupancy/$", occupancy.occupancy, name="location_occupancy"),
    re_path(
        r"^occupancy/room/(?P<room_id>\d+)/(?P<year>\d+)/$",
        occupancy.room_occupancy,
        name="room_occupancy",
    ),
    re_path(r"^calendar/$", occupancy.calendar, name="location_calendar"),
    re_path(r"^thanks/$", occupancy.thanks, name="location_thanks"),
    re_path(r"^today/$", occupancy.today, name="location_today"),
    re_path(r"^json/room/$", booking.RoomApiList.as_view(), name="json_room_list"),
    re_path(
        r"^json/room/(?P<room_id>\w+)/$",
        booking.RoomApiDetail.as_view(),
        name="json_room_detail",
    ),
    re_path(
        r"^edit/settings/$",
        location.LocationEditSettings,
        name="location_edit_settings",
    ),
    re_path(r"^edit/users/$", location.LocationEditUsers, name="location_edit_users"),
    re_path(
        r"^edit/content/$", location.LocationEditContent, name="location_edit_content"
    ),
    re_path(
        r"^edit/emails/$", location.LocationEditEmails, name="location_edit_emails"
    ),
    re_path(r"^edit/pages/$", location.LocationEditPages, name="location_edit_pages"),
    re_path(
        r"^edit/rooms/(?P<room_id>\d+)/$",
        location.LocationEditRoom,
        name="location_edit_room",
    ),
    re_path(r"^edit/rooms/new$", location.LocationNewRoom, name="location_new_room"),
    re_path(
        r"^edit/rooms/$", location.LocationManageRooms, name="location_manage_rooms"
    ),
    re_path(r"^email/current$", messages.current, name="location_email_current"),
    re_path(r"^email/stay$", messages.stay, name="location_email_stay"),
    re_path(r"^email/residents$", messages.residents, name="location_email_residents"),
    re_path(r"^email/test80085$", messages.test80085, name="location_email_test"),
    re_path(
        r"^email/unsubscribe$", messages.unsubscribe, name="location_email_unsubscribe"
    ),
    re_path(r"^email/announce$", messages.announce, name="location_email_announce"),
    # internal views
    re_path(
        r"^rooms_availabile_on_dates/$",
        occupancy.RoomsAvailableOnDates,
        name="rooms_available_on_dates",
    ),
    re_path(r"^booking/", include("core.urls.bookings")),
    re_path(r"^use/", include("core.urls.uses")),
    re_path(r"^manage/", include("core.urls.manage")),
    re_path(r"^events/", include("gather.urls")),
    # redirect from old 'reservation' paths
    re_path(r"^reservation/(?P<rest_of_path>(.+))/$", redirects.reservation_redirect),
]

urlpatterns = [
    re_path(r"^$", location.location_list, name="location_list"),
    re_path(r"^(?P<location_slug>[\w-]+)/", include(per_location_patterns)),
]
