from django.urls import re_path

from core.views.use import UseDetail

urlpatterns = [
    re_path(r"^(?P<use_id>\d+)/$", UseDetail, name="use_detail"),
    # re_path(r'^(?P<booking_id>\d+)/edit/$', BookingEdit, name='booking_edit'),
    # re_path(r'^(?P<booking_id>\d+)/delete/$', BookingDelete, name='booking_delete'),
    # re_path(r'^(?P<booking_id>\d+)/cancel/$', BookingCancel, name='booking_cancel'),
]
