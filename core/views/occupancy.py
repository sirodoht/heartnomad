import csv
import datetime
import logging
from decimal import Decimal

import dateutil
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import csrf_exempt

from core.booking_calendar import GuestCalendar
from core.decorators import resident_or_admin_required
from core.models import (
    Booking,
    Location,
    Payment,
    Resource,
    Subscription,
    Use,
)
from gather.tasks import published_events_today_local

logger = logging.getLogger(__name__)


def get_calendar_dates(month, year):
    month = int(month) if month else datetime.date.today().month
    year = int(year) if year else datetime.date.today().year

    # start date is first day of the month
    start = datetime.date(year, month, 1)
    # calculate end date by subtracting one day from the start of the next
    # month (saves us from having to reference how many days that month has)
    next_month = (month + 1) % 12
    if next_month == 0:
        next_month = 12
    next_months_year = year + 1 if next_month < month else year

    end = datetime.date(next_months_year, next_month, 1)
    next_month = end  # for clarity

    # also calculate the previous month for reference in the template
    prev_month = (month - 1) % 12
    if prev_month == 0:
        prev_month = 12

    prev_months_year = year - 1 if prev_month > month else year
    prev_month = datetime.date(prev_months_year, prev_month, 1)

    # returns datetime objects (start, end, next_month, prev_month) and ints (month, year)
    return start, end, next_month, prev_month, month, year


def today(request, location_slug):
    location = get_object_or_404(Location, slug=location_slug)
    # get all the bookings that intersect today (including those departing
    # and arriving today)
    today = timezone.now()
    bookings_today = (
        Booking.objects.filter(Q(status="confirmed") | Q(status="approved"))
        .exclude(depart__lt=today)
        .exclude(arrive__gt=today)
    )
    guests_today = []
    for r in bookings_today:
        guests_today.append(r.user)
    residents = location.residents()
    people_today = guests_today + list(residents)

    events_today = published_events_today_local(location)
    return render(
        request,
        "today.html",
        {"people_today": people_today, "events_today": events_today},
    )


def room_occupancy_month(room, month, year):
    logger.debug(room, month, year)
    start, end, next_month, prev_month, month, year = get_calendar_dates(month, year)

    # note the day parameter is meaningless
    uses = (
        Use.objects.filter(resource=room)
        .filter(status="confirmed")
        .exclude(depart__lt=start)
        .exclude(arrive__gt=end)
    )

    # payments *received* this month for this room
    payments_for_room = (
        Payment.objects.booking_payments_by_resource(room)
        .filter(payment_date__gte=start)
        .filter(payment_date__lte=end)
    )
    payments_cash = 0
    for p in payments_for_room:
        payments_cash += p.paid_amount

    nights_occupied = 0
    payments_accrual = 0
    outstanding_value = 0
    partial_paid_bookings = []
    total_comped_nights = 0
    total_comped_value = 0

    # not calculating:
    # payments this month for previous months
    # payments for this month FROM past months (except inasmuch as its captured in the payments_accrual)

    total_user_value = Decimal(0.0)
    net_to_house = Decimal(0.0)
    externalized_fees = Decimal(0.0)
    internal_fees = Decimal(0.0)
    # occupancy for room this month
    for u in uses:
        # in case this Booking crossed a month boundary, first calculate
        # nights of this Booking that took place this month
        if u.arrive >= start and u.depart <= end:
            nights_this_month = (u.depart - u.arrive).days
        elif u.arrive <= start and u.depart >= end:
            nights_this_month = (end - start).days
        elif u.arrive < start:
            nights_this_month = (u.depart - start).days
        elif u.depart > end:
            nights_this_month = (end - u.arrive).days

        # if it's the first of the month and the person left on the 1st, then
        # that's actually 0 days this month which we don't need to include.
        if nights_this_month == 0:
            continue

        nights_occupied += nights_this_month

        if u.booking.is_comped():
            total_comped_nights += nights_this_month
            total_comped_value += nights_this_month * u.booking.default_rate()
        else:
            total_user_value += (
                u.booking.bill.amount() / u.total_nights()
            ) * nights_this_month
            net_to_house += (
                u.booking.bill.to_house() / u.total_nights()
            ) * nights_this_month
            externalized_fees += (
                u.booking.bill.non_house_fees() / u.total_nights()
            ) * nights_this_month
            internal_fees += (
                u.booking.bill.house_fees() / u.total_nights()
            ) * nights_this_month

            if u.booking.payments():
                paid_rate = u.booking.bill.to_house() / u.total_nights()
                payments_accrual += nights_this_month * paid_rate

            # if a Booking rate is set to 0 is automatically gets counted as a comp
            if u.booking.bill.total_owed() > 0:
                outstanding_value += u.booking.bill.total_owed()
                partial_paid_bookings.append(u.booking.id)

    params = [
        month,
        year,
        round(payments_cash, 2),
        round(payments_accrual, 2),
        nights_occupied,
        room.quantity_between(start, end),
        partial_paid_bookings,
        total_comped_nights,
        outstanding_value,
        total_user_value,
        net_to_house,
        externalized_fees,
        internal_fees,
        round(total_comped_value, 2),
    ]
    return params


@resident_or_admin_required
def room_occupancy(request, location_slug, room_id, year):
    room = get_object_or_404(Resource, id=room_id)
    year = int(year)
    response = HttpResponse(content_type="text/csv")
    output_filename = "%s Occupancy Report %d.csv" % (room.name, year)
    response["Content-Disposition"] = f"attachment; filename={output_filename}"
    writer = csv.writer(response)
    if room.location.slug != location_slug:
        writer.writerow(["invalid room"])
        return response

    writer.writerow([str(year) + " Report for " + room.name])
    writer.writerow(
        [
            "Month",
            "Year",
            "Payments Cash",
            "Payments Accrual",
            "Nights Occupied",
            "Nights Available",
            "Partial Paid Bookings",
            "Comped Nights",
            "Outstanding Value",
            "Total User Value",
            "Net Value to House",
            "Externalized Fees",
            "Internal Fees",
            "Comped Value",
        ]
    )
    # we don't have data before 2012 or in the future
    if (year < 2012) or (year > datetime.date.today().year):
        return response

    for month in range(1, 13):
        params = room_occupancy_month(room, month, year)
        writer.writerow(params)

    return response


def monthly_occupant_report(location_slug, year, month):
    location = get_object_or_404(Location, slug=location_slug)
    start, end, next_month, prev_month, month, year = get_calendar_dates(month, year)

    occupants = {}
    occupants["residents"] = {}
    occupants["guests"] = {}
    occupants["members"] = {}
    messages = []

    # calculate datas for people this month (as relevant), including: name, email, total_nights, total_value, total_comped, owing, and reference ids
    for user in location.residents():
        if user in occupants["residents"]:
            messages.append(
                "user %d (%s %s) showed up in residents list twice. this shouldn't happen. the second instance was skipped."
                % (user.id, user.first_name, user.last_name)
            )
        else:
            occupants["residents"][user] = {
                "name": user.get_full_name(),
                "email": user.email,
                "total_nights": (end - start).days,
            }

    uses = (
        Use.objects.filter(location=location)
        .filter(status="confirmed")
        .exclude(depart__lt=start)
        .exclude(arrive__gt=end)
    )
    for use in uses:
        nights_this_month = use.nights_between(start, end)
        u = use.user
        comped_nights_this_month = 0
        owing = []
        effective_rate = use.booking.bill.subtotal_amount() / use.total_nights()
        value_this_month = nights_this_month * effective_rate
        if use.booking.is_comped():
            comped_nights_this_month = nights_this_month
        if use.booking.bill.total_owed() > 0:
            owing.append(use.booking.id)

        # now assemble it all
        if u not in occupants["guests"]:
            occupants["guests"][u] = {
                "name": u.get_full_name(),
                "email": u.email,
                "total_nights": nights_this_month,
                "total_value": value_this_month,
                "total_comped": comped_nights_this_month,
                "owing": owing,
                "ids": [use.booking.id],
            }
        else:
            occupants["guests"][u]["total_nights"] += nights_this_month
            occupants["guests"][u]["total_value"] += value_this_month
            occupants["guests"][u]["total_comped"] += comped_nights_this_month
            if owing:
                occupants["guests"][u]["owing"].append(owing)
            occupants["guests"][u]["ids"].append(use.booking.id)

    # check for subscriptions that were active for any days this month.
    subscriptions = list(
        Subscription.objects.active_subscriptions_between(start, end).filter(
            location=location
        )
    )
    for s in subscriptions:
        days_this_month = s.days_between(start, end)
        u = s.user
        comped_days_this_month = 0
        owing = None
        # for subscriptions, the 'value' is the sum of the effective daily rate
        # associated with the days of the bill(s) that occurred this month.
        bills_between = s.bills_between(start, end)
        value_this_month = 0
        logger.debug("subscription %d" % s.id)
        for b in bills_between:
            logger.debug(b.subtotal_amount())
            logger.debug(b.period_end)
            logger.debug(b.period_start)
            if (b.period_end - b.period_start).days > 0:
                effective_rate = (
                    b.subtotal_amount() / (b.period_end - b.period_start).days
                )
                value_this_bill_this_month = effective_rate * b.days_between(start, end)
                value_this_month += value_this_bill_this_month

            # also make a note if this subscription has any bills that have an
            # outstanding balance. we store the subscription not the bill,
            # since that's the way an admin would view it from the website, so
            # check for duplicates since there could be multiple unpaid but we
            # still are pointing people to the same subscription.
            if b.total_owed() > 0 and not owing:
                owing = b.subscription.id

            if b.amount() == 0:
                comped_days_this_month += b.days_between(start, end)

        # ok now asssemble the dicts!
        if u not in occupants["members"]:
            occupants["members"][u] = {
                "name": u.get_full_name(),
                "email": u.email,
                "total_nights": days_this_month,
                "total_value": value_this_month,
                "total_comped": comped_days_this_month,
                "owing": [owing],
                "ids": [s.id],
            }
        else:
            occupants["members"][u]["total_nights"] += nights_this_month
            occupants["members"][u]["total_value"] += value_this_month
            occupants["members"][u]["total_comped"] += comped_nights_this_month
            if owing:
                occupants["members"][u]["owing"].append(owing)
            occupants["members"][u]["ids"].append(s.id)

    messages.append(
        "If a membership has a weird total_value, it is likely because there was a discount or fee applied to an "
        + "individual bill. Check the membership page."
    )
    return occupants, messages


@resident_or_admin_required
def occupancy(request, location_slug):
    location = get_object_or_404(Location, slug=location_slug)
    month = request.GET.get("month")
    year = request.GET.get("year")

    start, end, next_month, prev_month, month, year = get_calendar_dates(month, year)

    # note the day parameter is meaningless
    report_date = datetime.date(year, month, 1)
    uses = (
        Use.objects.filter(location=location)
        .filter(status="confirmed")
        .exclude(depart__lt=start)
        .exclude(arrive__gt=end)
    )

    person_nights_data = []
    total_occupied_person_nights = 0
    total_income = 0
    total_comped_nights = 0
    total_comped_income = 0
    total_shared_nights = 0
    total_private_nights = 0
    unpaid_total = 0
    room_income = {}
    room_occupancy = {}
    income_for_this_month = 0
    income_for_future_months = 0
    income_from_past_months = 0
    income_for_past_months = 0
    paid_rate_discrepancy = 0
    payment_discrepancies = []
    paid_amount_missing = []
    room_income_occupancy = {}
    overall_occupancy = 0

    # JKS note: this section breaks down income by whether it is income for this
    # month, for future months, from past months, for past months, for this
    # month, etc... but it turns out that this gets almost impossible to track
    # because there's many edge cases causd by uses being edited,
    # appended to, partial refunds, etc. so, it's kind of fuzzy. if you try and
    # work on it, don't say i didn't warn you :).

    payments_this_month = (
        Payment.objects.booking_payments_by_location(location)
        .filter(payment_date__gte=start)
        .filter(payment_date__lte=end)
    )
    for p in payments_this_month:
        u = p.bill.bookingbill.booking.use
        nights_before_this_month = datetime.timedelta(0)
        nights_after_this_month = datetime.timedelta(0)
        if u.arrive < start and u.depart < start:
            # all nights for this booking were in a previous month
            nights_before_this_month = u.depart - u.arrive

        elif u.arrive < start and u.depart <= end:
            # only nights before and during this month, but night for this
            # month are calculated below so only tally the nights for before
            # this month here.
            nights_before_this_month = start - u.arrive

        elif u.arrive >= start and u.depart <= end:
            # only nights this month, don't need to calculate this here because
            # it's calculated below.
            continue

        elif u.arrive >= start and u.arrive <= end and u.depart > end:
            # some nights are after this month
            nights_after_this_month = u.depart - end

        elif u.arrive > end:
            # all nights are after this month
            nights_after_this_month = u.depart - u.arrive

        elif u.arrive < start and u.depart > end:
            # there are some days paid for this month that belong to the previous month
            nights_before_this_month = start - u.arrive
            nights_after_this_month = u.depart - end

        # in the event that there are multiple payments for a booking, this
        # will basically amortize each payment across all nights
        income_for_future_months += nights_after_this_month.days * (
            p.to_house() / (u.depart - u.arrive).days
        )
        income_for_past_months += nights_before_this_month.days * (
            p.to_house() / (u.depart - u.arrive).days
        )

    for u in uses:
        comp = False
        partial_payment = False
        total_owed = 0.0

        nights_this_month = u.nights_between(start, end)
        # if it's the first of the month and the person left on the 1st, then
        # that's actually 0 days this month which we don't need to include.
        if nights_this_month == 0:
            continue

        # XXX Note! get_rate() returns the base rate, but does not incorporate
        # any discounts. so we use subtotal_amount here.
        rate = u.booking.bill.subtotal_amount() / u.total_nights()

        room_occupancy[u.resource] = (
            room_occupancy.get(u.resource, 0) + nights_this_month
        )

        if u.booking.is_comped():
            total_comped_nights += nights_this_month
            total_comped_income += nights_this_month * u.booking.default_rate()
            comp = True
            unpaid = False
        else:
            # the bill has the amount that goes to the house after fees
            to_house_per_night = u.booking.bill.to_house() / u.total_nights()
            total_income += nights_this_month * to_house_per_night
            this_room_income = room_income.get(u.resource, 0)
            this_room_income += nights_this_month * to_house_per_night
            room_income[u.resource] = this_room_income

            # If there are payments, calculate the payment rate
            if u.booking.payments():
                paid_rate = (
                    u.booking.bill.total_paid() - u.booking.bill.non_house_fees()
                ) / u.total_nights()
                if paid_rate != rate:
                    logger.debug(
                        "booking %d has paid rate = $%d and rate set to $%d"
                        % (u.booking.id, paid_rate, rate)
                    )
                    paid_rate_discrepancy += nights_this_month * (paid_rate - rate)
                    payment_discrepancies.append(u.booking.id)

            # JKS this section tracks whether payment for this booking
            # were made in a prior month or in this month.
            if u.booking.is_paid():
                unpaid = False
                for p in u.booking.payments():
                    if p.payment_date.date() < start:
                        income_from_past_months += nights_this_month * (
                            p.to_house() / (u.depart - u.arrive).days
                        )
                    # if the payment was sometime this month, we account for
                    # it. if it was in a future month, we'll show it as "income
                    # for previous months" in that month. we skip it here.
                    elif p.payment_date.date() < end:
                        income_for_this_month += nights_this_month * (
                            p.to_house() / (u.depart - u.arrive).days
                        )
            else:
                unpaid_total += to_house_per_night * nights_this_month
                unpaid = True
                if u.booking.bill.total_owed() < u.booking.bill.amount():
                    partial_payment = True
                    total_owed = u.booking.bill.total_owed()

        person_nights_data.append(
            {
                "booking": u.booking,
                "nights_this_month": nights_this_month,
                "room": u.resource.name,
                "rate": rate,
                "partial_payment": partial_payment,
                "total_owed": total_owed,
                "total": nights_this_month * rate,
                "comp": comp,
                "unpaid": unpaid,
            }
        )
        total_occupied_person_nights += nights_this_month

    location_rooms = location.resources.all()
    total_reservable_days = 0
    reservable_days_per_room = {}
    for room in location_rooms:
        reservable_days_per_room[room] = room.quantity_between(start, end)

    total_income_for_this_month = income_for_this_month + income_from_past_months
    total_income_during_this_month = (
        income_for_this_month + income_for_future_months + income_for_past_months
    )
    total_by_rooms = sum(room_income.values())
    for room in location_rooms:
        # JKS: it is possible for this to be > 100% if admins overbook a room
        # or book it when it was not listed as available.
        if reservable_days_per_room.get(room, 0):
            room_occupancy_rate = (
                100
                * float(room_occupancy.get(room, 0))
                / reservable_days_per_room[room]
            )
        else:
            room_occupancy_rate = 0.0
        # tuple with income, num nights occupied, and % occupancy rate
        room_income_occupancy[room] = (
            room_income.get(room, 0),
            room_occupancy_rate,
            room_occupancy.get(room, 0),
            reservable_days_per_room.get(room, 0),
        )
        logger.debug(room.name)
        logger.debug(room_income_occupancy[room])
        total_reservable_days += reservable_days_per_room[room]
    overall_occupancy = 0
    if total_reservable_days > 0:
        overall_occupancy = (
            100 * float(total_occupied_person_nights) / total_reservable_days
        )

    return render(
        request,
        "occupancy.html",
        {
            "data": person_nights_data,
            "location": location,
            "total_occupied_person_nights": total_occupied_person_nights,
            "total_income": total_income,
            "unpaid_total": unpaid_total,
            "total_reservable_days": total_reservable_days,
            "overall_occupancy": overall_occupancy,
            "total_shared_nights": total_shared_nights,
            "total_private_nights": total_private_nights,
            "total_comped_income": total_comped_income,
            "total_comped_nights": total_comped_nights,
            "next_month": next_month,
            "prev_month": prev_month,
            "report_date": report_date,
            "room_income_occupancy": room_income_occupancy,
            "income_for_this_month": income_for_this_month,
            "income_for_future_months": income_for_future_months,
            "income_from_past_months": income_from_past_months,
            "income_for_past_months": income_for_past_months,
            "total_income_for_this_month": total_income_for_this_month,
            "total_by_rooms": total_by_rooms,
            "paid_rate_discrepancy": paid_rate_discrepancy,
            "payment_discrepancies": payment_discrepancies,
            "total_income_during_this_month": total_income_during_this_month,
            "paid_amount_missing": paid_amount_missing,
            "average_guests_per_day": float(total_occupied_person_nights)
            / (end - start).days,
        },
    )


@login_required
def manage_today(request, location_slug):
    location = get_object_or_404(Location, slug=location_slug)
    today = timezone.localtime(timezone.now())

    departing_today = (
        Use.objects.filter(Q(status="confirmed") | Q(status="approved"))
        .filter(location=location)
        .filter(depart=today)
    )

    arriving_today = (
        Use.objects.filter(Q(status="confirmed") | Q(status="approved"))
        .filter(location=location)
        .filter(arrive=today)
    )

    events_today = published_events_today_local(location)

    return render(
        request,
        "location_manage_today.html",
        {
            "location": location,
            "arriving_today": arriving_today,
            "departing_today": departing_today,
            "events_today": events_today,
        },
    )


@login_required
def calendar(request, location_slug):
    location = get_object_or_404(Location, slug=location_slug)
    month = request.GET.get("month")
    year = request.GET.get("year")

    start, end, next_month, prev_month, month, year = get_calendar_dates(month, year)
    report_date = datetime.date(year, month, 1)

    uses = (
        Use.objects.filter(Q(status="confirmed") | Q(status="approved"))
        .filter(location=location)
        .exclude(depart__lt=start)
        .exclude(arrive__gt=end)
        .order_by("arrive")
    )

    rooms = Resource.objects.filter(location=location)
    uses_by_room = []
    empty_rooms = 0

    # this is tracked here to help us determine what height the timeline div
    # should be. it's kind of a hack.
    num_rows_in_chart = 0
    for room in rooms:
        num_rows_in_chart += room.max_daily_capacities_between(start, end)

    any_uses = len(uses) != 0

    for room in rooms:
        uses_this_room = []

        uses_list_this_room = list(uses.filter(resource=room))

        if len(uses_list_this_room) == 0:
            empty_rooms += 1
            num_rows_in_chart -= room.max_daily_capacities_between(start, end)

        else:
            for u in uses_list_this_room:
                display_start = start if u.arrive < start else u.arrive
                display_end = end if u.depart > end else u.depart
                uses_this_room.append(
                    {
                        "use": u,
                        "display_start": display_start,
                        "display_end": display_end,
                    }
                )

            uses_by_room.append((room, uses_this_room))

    logger.debug("Uses by Room for calendar view:")
    logger.debug(uses_by_room)

    # create the calendar object
    guest_calendar = GuestCalendar(uses, year, month, location).formatmonth(year, month)

    return render(
        request,
        "calendar.html",
        {
            "uses": uses,
            "uses_by_room": uses_by_room,
            "month_start": start,
            "month_end": end,
            "next_month": next_month,
            "prev_month": prev_month,
            "rows_in_chart": num_rows_in_chart,
            "report_date": report_date,
            "location": location,
            "empty_rooms": empty_rooms,
            "any_uses": any_uses,
            "calendar": mark_safe(guest_calendar),
        },
    )


def thanks(request, location_slug):
    # TODO generate receipt
    return render(request, "thanks.html")


def date_range_to_list(start, end):
    the_day = start
    date_list = []
    while the_day < end:
        date_list.append(the_day)
        the_day = the_day + datetime.timedelta(1)
    return date_list


@csrf_exempt
def RoomsAvailableOnDates(request, location_slug):
    """
    Args:
        request (http request obj): Request object sent from ajax request, includes arrive, depart and room data
        location_slug (string): name of location

    Returns:
        Boolean: True if room is available. False if not available.

    """
    # Check the room on the admin booking page to see if its available
    location = get_object_or_404(Location, slug=location_slug)
    # Check if the room is available for all dates in the booking
    arrive = dateutil.parser(request.POST["arrive"]).date
    depart = dateutil.parser(request.POST["depart"]).date

    free_rooms = location.rooms_free(arrive, depart)
    rooms_capacity = {}
    for room in location.rooms_with_future_capacity():
        if room in free_rooms:
            rooms_capacity[room.name] = {"available": True, "id": room.id}
        else:
            rooms_capacity[room.name] = {"available": False, "id": room.id}
    return JsonResponse({"rooms_capacity": rooms_capacity})
