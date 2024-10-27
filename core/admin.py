from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from core import models
from core.emails import messages as email_messages
from gather import models as gather_models


@admin.register(models.EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    exclude = ("creator",)

    def save_model(self, request, obj, form, change):
        obj.creator = request.user
        obj.save()


@admin.register(models.LocationEmailTemplate)
class LocationEmailTemplateAdmin(admin.ModelAdmin):
    list_display = ("location", "key")


class EventAdminGroupInline(admin.TabularInline):
    model = gather_models.EventAdminGroup
    filter_horizontal = ["users"]
    raw_id_fields = ("users",)


class CapacityChangeAdminInline(admin.TabularInline):
    model = models.CapacityChange
    ordering = ("start_date",)


@admin.register(models.Resource)
class ResourceAdmin(admin.ModelAdmin):
    inlines = [CapacityChangeAdminInline]
    save_as = True


class ResourceAdminInline(admin.TabularInline):
    model = models.Resource
    extra = 0


@admin.register(models.Location)
class LocationAdmin(admin.ModelAdmin):
    def send_admin_daily_update(self, request, queryset):
        for res in queryset:
            email_messages.admin_daily_update(res)
        msg = gen_message(queryset, "email", "emails", "sent")
        self.message_user(request, msg)

    def send_guests_residents_daily_update(self, request, queryset):
        for res in queryset:
            email_messages.guests_residents_daily_update(res)
        msg = gen_message(queryset, "email", "emails", "sent")
        self.message_user(request, msg)

    save_as = True
    list_display = ("name", "address")
    list_filter = ("name",)
    filter_horizontal = ["house_admins", "readonly_admins"]
    actions = ["send_admin_daily_update", "send_guests_residents_daily_update"]
    raw_id_fields = ("house_admins", "readonly_admins")

    inlines = [ResourceAdminInline]
    if "gather" in settings.INSTALLED_APPS:
        inlines.append(EventAdminGroupInline)


@admin.register(models.Bill)
class BillAdmin(admin.ModelAdmin): ...


@admin.register(models.Payment)
class PaymentAdmin(admin.ModelAdmin):
    def user(self):
        if self.user:
            return f"""<a href="/people/{self.user.username}">{self.user.first_name} {self.user.last_name}</a> ({self.user.username})"""
        else:
            return """None"""

    user.allow_tags = True

    def booking(self):
        b = self.bill.bookingbill.booking
        return f"""<a href="/locations/{b.use.location.slug}/booking/{b.id}/">{b}"""

    booking.allow_tags = True

    model = models.Payment
    list_display = ("payment_date", user, "payment_method", "paid_amount")
    list_filter = ("payment_method",)
    ordering = ["-payment_date"]


class PaymentInline(admin.TabularInline):
    model = models.Payment
    extra = 0


@admin.register(models.BillLineItem)
class BillLineItemAdmin(admin.ModelAdmin):
    list_display = ("id", "description", "amount", "paid_by_house")
    list_filter = ("fee", "paid_by_house")


class BillLineItemInline(admin.TabularInline):
    model = models.BillLineItem
    fields = ("fee", "description", "amount", "paid_by_house")
    readonly_fields = ("fee",)
    extra = 0


class BillInline(admin.StackedInline):
    model = models.Bill
    extra = 0
    inlines = [BillLineItemInline, PaymentInline]


def gen_message(queryset, noun, pl_noun, suffix):
    if len(queryset) == 1:
        prefix = f"1 {noun} was"
    else:
        prefix = "%d %s were" % (len(queryset), pl_noun)
    msg = prefix + " " + suffix + "."
    return msg


@admin.register(models.UseTransaction)
class UseTransactionAdmin(admin.ModelAdmin): ...


@admin.register(models.Use)
class UseAdmin(admin.ModelAdmin): ...


@admin.register(models.Booking)
class BookingAdmin(admin.ModelAdmin):
    def rate(self):
        if self.rate is None:
            return None
        return "$%d" % self.rate

    def value(self):
        return "$%d" % self.base_value()

    def bill(self):
        return "$%d" % self.bill.amount()

    def fees(self):
        return "$%d" % self.bill.non_house_fees()

    def to_house(self):
        return "$%d" % self.to_house()

    def paid(self):
        return "$%d" % self.bill.total_paid()

    def user_profile(self):
        return f"""<a href="/people/{self.use.user.username}">{self.use.user.first_name} {self.use.user.last_name}</a> ({self.use.user.username})"""

    user_profile.allow_tags = True

    def send_receipt(self, request, queryset):
        success_list = []
        failure_list = []
        for res in queryset:
            if email_messages.send_booking_receipt(res):
                success_list.append(str(res.id))
            else:
                failure_list.append(str(res.id))
        msg = ""
        if len(success_list) > 0:
            msg += "Receipts sent for booking(s) {}. ".format(",".join(success_list))
        if len(failure_list) > 0:
            msg += "Receipt sending failed for booking(s) {}. (Make sure all payment information has been entered in the booking details and that the status of the booking is either unpaid or paid.)".format(
                ",".join(failure_list)
            )
        self.message_user(request, msg)

    def send_invoice(self, request, queryset):
        for res in queryset:
            email_messages.send_invoice(res)
        msg = gen_message(queryset, "invoice", "invoices", "sent")
        self.message_user(request, msg)

    def send_new_booking_notify(self, request, queryset):
        for res in queryset:
            email_messages.new_booking_notify(res)
        msg = gen_message(queryset, "email", "emails", "sent")
        self.message_user(request, msg)

    def send_updated_booking_notify(self, request, queryset):
        for res in queryset:
            email_messages.updated_booking_notify(res)
        msg = gen_message(queryset, "email", "emails", "sent")
        self.message_user(request, msg)

    def send_guest_welcome(self, request, queryset):
        for res in queryset:
            email_messages.guest_welcome(res)
        msg = gen_message(queryset, "email", "emails", "sent")
        self.message_user(request, msg)

    def mark_as_comp(self, request, queryset):
        for res in queryset:
            res.comp()
        msg = gen_message(queryset, "booking", "bookings", "marked as comp")
        self.message_user(request, msg)

    def revert_to_pending(self, request, queryset):
        for res in queryset:
            res.pending()
        msg = gen_message(queryset, "booking", "bookings", "reverted to pending")
        self.message_user(request, msg)

    def approve(self, request, queryset):
        for res in queryset:
            res.approve()
        msg = gen_message(queryset, "booking", "bookings", "approved")
        self.message_user(request, msg)

    def confirm(self, request, queryset):
        for res in queryset:
            res.confirm()
        msg = gen_message(queryset, "booking", "bookings", "confirmed")
        self.message_user(request, msg)

    def cancel(self, request, queryset):
        for res in queryset:
            res.cancel()
        msg = gen_message(queryset, "booking", "bookings", "canceled")
        self.message_user(request, msg)

    def reset_rate(self, request, queryset):
        for res in queryset:
            res.reset_rate()
        msg = gen_message(queryset, "booking", "bookings", "set to default rate")
        self.message_user(request, msg)

    def recalculate_bill(self, request, queryset):
        for res in queryset:
            res.generate_bill()
        msg = gen_message(queryset, "bill", "bills", "recalculated")
        self.message_user(request, msg)

    list_filter = ("status_deprecated", "location_deprecated")
    list_display = (
        "id",
        user_profile,
        "status_deprecated",
        "arrive_deprecated",
        "depart_deprecated",
        "resource_deprecated",
        rate,
        fees,
        bill,
        to_house,
        paid,
    )
    search_fields = (
        "use__user__username",
        "use__user__first_name",
        "use__user__last_name",
        "id",
    )
    ordering = ["-arrive_deprecated", "id"]
    actions = [
        "send_guest_welcome",
        "send_new_booking_notify",
        "send_updated_booking_notify",
        "send_receipt",
        "send_invoice",
        "recalculate_bill",
        "mark_as_comp",
        "reset_rate",
        "revert_to_pending",
        "approve",
        "confirm",
        "cancel",
    ]
    save_as = True


class UserProfileInline(admin.StackedInline):
    model = models.UserProfile


admin.site.unregister(User)


@admin.register(User)
class UserProfileAdmin(UserAdmin):
    actions = ["create_primary_drft_account"]

    def create_primary_drft_account(self, request, queryset):
        for user in queryset:
            try:
                drft_account = user.profile._has_primary_drft_account()
                if not drft_account:
                    drft_account = user.profile.primary_drft_account()
                    self.message_user(
                        request,
                        "Primary DRFT Account (id %d) created for %s %s"
                        % (drft_account.pk, user.first_name, user.last_name),
                    )
                else:
                    self.message_user(
                        request,
                        "User %s %s already had a primary DRFT account (id %d)"
                        % (user.first_name, user.last_name, drft_account.pk),
                        level=messages.WARNING,
                    )
            except Exception as e:
                self.message_user(request, e, level=messages.ERROR)

    create_primary_drft_account.short_description = (
        "Create primary DRFT account for seleted users"
    )

    inlines = [UserProfileInline]
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "is_staff",
        "date_joined",
        "last_login",
    )


class LocationFlatPageInline(admin.StackedInline):
    model = models.LocationFlatPage


@admin.register(models.LocationMenu)
class LocationMenuAdmin(admin.ModelAdmin):
    inlines = [LocationFlatPageInline]
    list_display = ("location", "name")


@admin.register(models.UserNote)
class UserNoteAdmin(admin.ModelAdmin): ...


@admin.register(models.Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = (
        "membership_type",
        "user",
        "start_date",
        "end_date",
    )


@admin.register(models.CapacityChange)
class CapacityChangeAdmin(admin.ModelAdmin):
    list_display = ("resource", "start_date", "quantity")


@admin.register(models.HouseAccount)
class HouseAccountAdmin(admin.ModelAdmin): ...


@admin.register(models.Backing)
class BackingAdmin(admin.ModelAdmin):
    model = models.Backing
    raw_id_fields = ("users",)
    list_filter = ("resource",)


@admin.register(models.Fee)
class FeeAdmin(admin.ModelAdmin): ...


@admin.register(models.LocationFee)
class LocationFeeAdmin(admin.ModelAdmin): ...
