from django.urls import re_path

from core.views import billing, booking_management, occupancy

# custom management patterns
urlpatterns = [
    re_path(r"^payments/$", billing.payments_today, name="location_payments_today"),
    re_path(
        r"^payments/(?P<year>\d+)/(?P<month>\d+)$",
        billing.payments,
        name="location_payments",
    ),
    re_path(r"^today/$", occupancy.manage_today, name="manage_today"),
    re_path(
        r"bookings/$", booking_management.BookingManageList, name="booking_manage_list"
    ),
    re_path(
        r"booking/create/$",
        booking_management.BookingManageCreate,
        name="booking_manage_create",
    ),
    re_path(
        r"booking/(?P<booking_id>\d+)/$",
        booking_management.BookingManage,
        name="booking_manage",
    ),
    re_path(
        r"booking/(?P<booking_id>\d+)/action/$",
        booking_management.BookingManageAction,
        name="booking_manage_action",
    ),
    re_path(
        r"booking/(?P<booking_id>\d+)/paywithdrft/$",
        booking_management.BookingManagePayWithDrft,
        name="booking_manage_pay_drft",
    ),
    re_path(
        r"booking/(?P<booking_id>\d+)/togglecomp/$",
        booking_management.BookingToggleComp,
        name="booking_toggle_comp",
    ),
    re_path(
        r"booking/(?P<booking_id>\d+)/sendreceipt/$",
        booking_management.BookingSendReceipt,
        name="booking_send_receipt",
    ),
    re_path(
        r"booking/(?P<booking_id>\d+)/sendwelcome/$",
        booking_management.BookingSendWelcomeEmail,
        name="booking_send_welcome",
    ),
    re_path(
        r"booking/(?P<booking_id>\d+)/sendmail/$",
        booking_management.BookingSendMail,
        name="booking_send_mail",
    ),
    re_path(r"bill/(?P<bill_id>\d+)/charge/$", billing.BillCharge, name="bill_charge"),
    re_path(
        r"bill/(?P<bill_id>\d+)/payment/$", billing.ManagePayment, name="manage_payment"
    ),
    re_path(
        r"bill/(?P<bill_id>\d+)/addbillitem/$",
        billing.AddBillLineItem,
        name="add_bill_item",
    ),
    re_path(
        r"bill/(?P<bill_id>\d+)/deletebillitem/$",
        billing.DeleteBillLineItem,
        name="delete_bill_item",
    ),
    re_path(
        r"bill/(?P<bill_id>\d+)/recalculate/$",
        billing.RecalculateBill,
        name="recalculate_bill",
    ),
    re_path(
        r"booking/(?P<booking_id>\d+)/edit/$",
        booking_management.BookingManageEdit,
        name="booking_manage_edit",
    ),
]
