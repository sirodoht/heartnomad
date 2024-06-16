import datetime
import logging
import time
from decimal import Decimal

import stripe
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from stripe.error import CardError

from modernomad.core import payment_gateway
from modernomad.core.decorators import house_admin_required, resident_or_admin_required
from modernomad.core.emails.messages import (
    admin_new_subscription_notify,
    send_booking_receipt,
    send_from_location_address,
    send_subscription_receipt,
    subscription_note_notify,
    updated_booking_notify,
)
from modernomad.core.forms import (
    AdminSubscriptionForm,
    PaymentForm,
    SubscriptionEmailTemplateForm,
)
from modernomad.core.models import (
    Bill,
    BillLineItem,
    Booking,
    EmailTemplate,
    Location,
    LocationFee,
    Payment,
    Subscription,
    SubscriptionNote,
    Use,
    UserNote,
)
from modernomad.core.tasks import guest_welcome
from modernomad.core.views import occupancy

logger = logging.getLogger(__name__)


@require_POST
@login_required
def create_checkout_session(request, username):
    # check permissions
    user = get_object_or_404(User, username=username)
    if request.user != user:
        messages.info(
            request,
            (
                "You are not authorized to add a credit card to this page. "
                "Please log in or use the 3rd party."
            ),
        )
        return HttpResponseRedirect("/404")

    try:
        stripe.api_key = settings.STRIPE_SECRET_KEY

        # check if user exists on stripe
        if user.profile.customer_id:
            customer = stripe.Customer.retrieve(user.profile.customer_id)
        else:
            customer = stripe.Customer.create(
                email=user.email, name=f"{user.first_name} {user.last_name}"
            )
            user.profile.customer_id = customer.id
            user.profile.save()

        checkout_session = stripe.checkout.Session.create(
            mode="setup",
            currency="usd",
            customer=customer.id,
            success_url=f"{settings.CANONICAL_URL}/people/{user.username}/checkout-success/",
            cancel_url=f"{settings.CANONICAL_URL}/people/{user.username}/",
        )
    except Exception as e:
        messages.info(
            request,
            (
                '<span class="text-danger">Drat, '
                f"there was a problem with our payment processor: <em>{e}</em></span>"
            ),
        )
        return redirect("user_detail", user.username)

    # response
    response = HttpResponseRedirect(checkout_session.url)
    response.status_code = 303
    return response


@login_required
def checkout_success(request, username):
    # check permissions
    user = get_object_or_404(User, username=username)

    booking_id = request.POST.get("res-id", False)
    if booking_id:
        booking = Booking.objects.get(id=booking_id)

    if (
        request.user != user
        and request.user not in booking.use.location.house_admins.all()
    ):
        messages.info(
            request,
            (
                "You are not authorized to add a credit card to this page. "
                "Please log in or use the 3rd party."
            ),
        )
        return HttpResponseRedirect("/404")

    # if booking
    booking_id = request.POST.get("res-id")
    if booking_id:
        booking = Booking.objects.get(id=booking_id)

    messages.info(request, "Thanks! Your card has been saved.")

    # booking continued
    if booking_id and booking.use.status == Use.APPROVED:
        updated_booking_notify(booking)
        return HttpResponseRedirect(
            reverse("booking_detail", args=(booking.use.location.slug, booking.id))
        )

    return HttpResponseRedirect("/people/%s" % user.username)


@login_required
def user_delete_card(request, username):
    # check permissions
    user = get_object_or_404(User, username=username)
    if request.user != user:
        messages.info(
            request,
            "You are not authorized to change this. Please log in or use the 3rd party.",
        )
        return HttpResponseRedirect("/404")

    try:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        stripe.Customer.delete(user.profile.customer_id)
    except Exception as e:
        messages.info(
            request,
            (
                '<span class="text-danger">Drat, '
                f"there was a problem with our payment processor: <em>{e}</em></span>"
            ),
        )
        return redirect("user_detail", user.username)

    user.profile.customer_id = None
    user.profile.save()

    messages.info(request, "Card deleted.")
    return HttpResponseRedirect("/people/%s" % user.username)


@house_admin_required
def ManagePayment(request, location_slug, bill_id):
    if request.method != "POST":
        return HttpResponseRedirect("/404")
    location = get_object_or_404(Location, slug=location_slug)
    bill = get_object_or_404(Bill, id=bill_id)

    logger.debug(request.POST)
    action = request.POST.get("action")
    if action == "Submit":
        # process a refund
        payment_id = request.POST.get("payment_id")
        payment = get_object_or_404(Payment, id=payment_id)
        refund_amount = request.POST.get("refund-amount")
        logger.debug(refund_amount)
        logger.debug(payment.net_paid())
        if Decimal(refund_amount) > Decimal(payment.net_paid()):
            messages.add_message(
                request, messages.INFO, "Cannot refund more than payment balance"
            )
        else:
            payment_gateway.issue_refund(payment, refund_amount)
            if bill.is_booking_bill():
                messages.add_message(
                    request,
                    messages.INFO,
                    "A refund for $%d was applied." % (Decimal(refund_amount)),
                )
            else:
                messages.add_message(
                    request,
                    messages.INFO,
                    "A refund for $%d was applied to the %s billing cycle."
                    % (
                        Decimal(refund_amount),
                        bill.subscriptionbill.period_start.strftime("%B %d, %Y"),
                    ),
                )
    elif action == "Save":
        logger.debug("saving record of external payment")
        # record a manual payment
        payment_method = request.POST.get("payment_method").strip().title()
        paid_amount = request.POST.get("paid_amount").strip()
        # JKS we store user = None for cash payments since we don't know for
        # certain *who* it was that made the payment. in the future, we could
        # allow admins to enter who made the payment, if desired.
        pmt = Payment.objects.create(
            payment_method=payment_method,
            paid_amount=paid_amount,
            bill=bill,
            user=None,
            transaction_id="Manual",
        )
        if bill.is_booking_bill():
            messages.add_message(request, messages.INFO, "Manual payment recorded")
        else:
            messages.add_message(
                request,
                messages.INFO,
                "A manual payment for $%d was applied to the %s billing cycle"
                % (
                    Decimal(paid_amount),
                    bill.subscriptionbill.period_start.strftime("%B %d, %Y"),
                ),
            )

    # JKS this is a little inelegant as it assumes that this page will always
    # a) want to redirect to a manage page and b) that there are only two types
    # of bills. this should be abstracted at some point.
    if bill.is_booking_bill():
        return HttpResponseRedirect(
            reverse("booking_manage", args=(location_slug, bill.bookingbill.booking.id))
        )
    else:
        return HttpResponseRedirect(
            reverse(
                "subscription_manage_detail",
                args=(location_slug, bill.subscriptionbill.subscription.id),
            )
        )


@house_admin_required
def SubscriptionSendReceipt(request, location_slug, subscription_id, bill_id):
    if request.method != "POST":
        return HttpResponseRedirect("/404")
    location = get_object_or_404(Location, slug=location_slug)
    subscription = Subscription.objects.get(id=subscription_id)
    bill = Bill.objects.get(id=bill_id)
    if bill.is_paid():
        status = send_subscription_receipt(subscription, bill)
        if status is not False:
            messages.add_message(request, messages.INFO, "A receipt was sent.")
        else:
            messages.add_message(
                request,
                messages.INFO,
                "Hmm, there was a problem and the receipt was not sent. Please contact an administrator.",
            )
    else:
        messages.add_message(
            request,
            messages.INFO,
            "This booking has not been paid, so the receipt was not sent.",
        )
    return HttpResponseRedirect(
        reverse("subscription_manage_detail", args=(location_slug, subscription_id))
    )


@house_admin_required
def RecalculateBill(request, location_slug, bill_id):
    if request.method != "POST":
        return HttpResponseRedirect("/404")
    location = get_object_or_404(Location, slug=location_slug)
    bill = get_object_or_404(Bill, id=bill_id)

    # what kind of bill is this?
    if bill.is_booking_bill():
        booking = bill.bookingbill.booking
        reset_suppressed = request.POST.get("reset_suppressed")
        if reset_suppressed == "true":
            booking.generate_bill(reset_suppressed=True)
        else:
            booking.generate_bill()
        messages.add_message(request, messages.INFO, "The bill has been recalculated.")
        return HttpResponseRedirect(
            reverse("booking_manage", args=(location.slug, booking.id))
        )
    elif bill.is_subscription_bill():
        subscription = bill.subscriptionbill.subscription
        subscription.generate_bill()
        messages.add_message(request, messages.INFO, "The bill has been recalculated.")
        return HttpResponseRedirect(
            reverse("subscription_manage_detail", args=(location.slug, subscription.id))
        )
    else:
        raise Exception("Unrecognized bill object")


@house_admin_required
def DeleteBillLineItem(request, location_slug, bill_id):
    if request.method != "POST":
        return HttpResponseRedirect("/404")
    location = get_object_or_404(Location, slug=location_slug)
    bill = get_object_or_404(Bill, pk=bill_id)

    if bill.is_booking_bill():
        booking = bill.bookingbill.booking
        logger.debug("in delete bill line item")
        logger.debug(request.POST)
        item_id = int(request.POST.get("payment_id"))
        line_item = BillLineItem.objects.get(id=item_id)
        line_item.delete()
        if line_item.fee:
            booking.suppress_fee(line_item)
        booking.generate_bill()
        messages.add_message(request, messages.INFO, "The line item was deleted.")
        return HttpResponseRedirect(
            reverse("booking_manage", args=(location.slug, booking.id))
        )
    elif bill.is_subscription_bill():
        subscription = bill.subscriptionbill.subscription
        logger.debug("in delete bill line item")
        logger.debug(request.POST)
        item_id = int(request.POST.get("payment_id"))
        line_item = BillLineItem.objects.get(id=item_id)
        line_item.delete()
        # subscriptions don't support external fees yet but if we add this,
        # then we should include the ability to suppress a fee. until then this won't work.
        # if line_item.fee:
        #    subscription.suppress_fee(line_item)
        subscription.generate_bill(target_date=bill.subscriptionbill.period_start)

        messages.add_message(
            request,
            messages.INFO,
            "The line item was deleted from the bill for %s."
            % (bill.subscriptionbill.period_start.strftime("%B %Y")),
        )
        return HttpResponseRedirect(
            reverse("subscription_manage_detail", args=(location.slug, subscription.id))
        )
    else:
        raise Exception("Unrecognized bill object")


@house_admin_required
def BillCharge(request, location_slug, bill_id):
    if request.method != "POST":
        return HttpResponseRedirect("/404")
    location = get_object_or_404(Location, slug=location_slug)
    bill = get_object_or_404(Bill, pk=bill_id)

    logger.debug(request.POST)
    # how much to charge?
    charge_amount_dollars = Decimal(request.POST.get("charge-amount"))
    logger.debug("request to charge user $%d" % charge_amount_dollars)
    if charge_amount_dollars > bill.total_owed():
        messages.add_message(
            request,
            messages.INFO,
            "Cannot charge more than remaining amount owed ($%d was requested on $%d owed)"
            % (charge_amount_dollars, bill.total_owed()),
        )
        return HttpResponseRedirect(
            reverse(
                "subscription_manage_detail",
                args=(location.slug, bill.subscriptionbill.subscription.id),
            )
        )

    if bill.is_booking_bill():
        user = bill.bookingbill.booking.user
        reference = "%d booking ref#%d" % (location.name, bill.bookingbill.booking.id)
    elif bill.is_subscription_bill():
        user = bill.subscriptionbill.subscription.user
        reference = "%s subscription ref#%d.%d monthly" % (
            location.name,
            bill.subscriptionbill.subscription.id,
            bill.id,
        )
    else:
        raise Exception("Unknown bill type. Cannot determine user.")

    try:
        payment = payment_gateway.charge_user(
            user, bill, charge_amount_dollars, reference
        )
    except CardError as e:
        messages.add_message(
            request, messages.INFO, "Charge failed with the following error: %s" % e
        )
        if bill.is_booking_bill():
            return HttpResponseRedirect(
                reverse(
                    "booking_manage", args=(location_slug, bill.bookingbill.booking.id)
                )
            )
        else:
            return HttpResponseRedirect(
                reverse(
                    "subscription_manage_detail",
                    args=(location_slug, bill.subscriptionbill.subscription.id),
                )
            )

    if bill.is_booking_bill():
        messages.add_message(request, messages.INFO, "The card was charged.")
        return HttpResponseRedirect(
            reverse("booking_manage", args=(location_slug, bill.bookingbill.booking.id))
        )
    else:
        messages.add_message(
            request,
            messages.INFO,
            "The card was charged. You must manually send the user their receipt. Please do so from the %s bill detail page."
            % bill.subscriptionbill.period_start.strftime("%B %d, %Y"),
        )
        return HttpResponseRedirect(
            reverse(
                "subscription_manage_detail",
                args=(location_slug, bill.subscriptionbill.subscription.id),
            )
        )


@house_admin_required
def AddBillLineItem(request, location_slug, bill_id):
    # can be used to apply a discount or a one time charge for, for example, a
    # cleaning fee.
    if request.method != "POST":
        return HttpResponseRedirect("/404")
    location = get_object_or_404(Location, slug=location_slug)
    bill = get_object_or_404(Bill, pk=bill_id)

    reason = request.POST.get("reason")
    calculation_type = request.POST.get("calculation_type")
    if request.POST.get("discount"):
        line_item_type = "discount"
    else:
        line_item_type = "fee"
    if line_item_type == "discount":
        if calculation_type == "absolute":
            reason = "Discount: " + reason
            amount = -Decimal(request.POST.get("discount"))
        elif calculation_type == "percent":
            percent = Decimal(request.POST.get("discount")) / 100
            reason = "Discount (%s%%): %s" % (percent * Decimal(100.0), reason)
            if percent < 0.0 or percent > 100.0:
                messages.add_message(
                    request, messages.INFO, "Invalid percent value given."
                )
                return HttpResponseRedirect(
                    reverse("booking_manage", args=(location.slug, booking_id))
                )
            amount = -(bill.subtotal_amount() * percent)
        else:
            messages.add_message(request, messages.INFO, "Invalid discount type.")
            return HttpResponseRedirect(
                reverse("booking_manage", args=(location.slug, booking_id))
            )
    else:
        # then it's a fee
        if calculation_type == "absolute":
            reason = "Fee: " + reason
            amount = float(request.POST.get("extra_fee"))
        elif calculation_type == "percent":
            percent = Decimal(request.POST.get("extra_fee")) / 100
            reason = "Fee (%s%%): %s" % (percent * Decimal(100.0), reason)
            if percent < 0.0 or percent > 100.0:
                messages.add_message(
                    request, messages.INFO, "Invalid percent value given."
                )
                return HttpResponseRedirect(
                    reverse("booking_manage", args=(location.slug, booking_id))
                )
            amount = bill.subtotal_amount() * percent
        else:
            messages.add_message(request, messages.INFO, "Invalid fee type.")
            return HttpResponseRedirect(
                reverse("booking_manage", args=(location.slug, booking_id))
            )

    new_line_item = BillLineItem(
        description=reason, amount=amount, paid_by_house=False, custom=True
    )
    new_line_item.bill = bill
    new_line_item.save()
    # regenerate the bill now that we've applied some new fees (even if the
    # rate has not changed, other percentage-based fees may be affected by this
    # new line item)
    if bill.is_booking_bill():
        booking = bill.bookingbill.booking
        booking.generate_bill()
        messages.add_message(
            request, messages.INFO, "The %s was added." % line_item_type
        )
        return HttpResponseRedirect(
            reverse("booking_manage", args=(location.slug, booking.id))
        )
    elif bill.is_subscription_bill():
        subscription = bill.subscriptionbill.subscription
        subscription.generate_bill(target_date=bill.subscriptionbill.period_start)
        messages.add_message(
            request,
            messages.INFO,
            "The %s was added to the bill for %s."
            % (line_item_type, bill.subscriptionbill.period_start.strftime("%B %Y")),
        )
        return HttpResponseRedirect(
            reverse("subscription_manage_detail", args=(location.slug, subscription.id))
        )
    else:
        raise Exception("Unrecognized bill object")


def _assemble_and_send_email(location_slug, post):
    location = get_object_or_404(Location, slug=location_slug)
    subject = post.get("subject")
    recipient = [post.get("recipient")]
    body = post.get("body") + "\n\n" + post.get("footer")
    # TODO - This isn't fully implemented yet -JLS
    send_from_location_address(subject, body, None, recipient, location)


@house_admin_required
def SubscriptionSendMail(request, location_slug, subscription_id):
    if request.method != "POST":
        return HttpResponseRedirect("/404")

    _assemble_and_send_email(location_slug, request.POST)
    messages.add_message(request, messages.INFO, "Your message was sent.")
    return HttpResponseRedirect(
        reverse("subscription_manage_detail", args=(location_slug, subscription_id))
    )


@resident_or_admin_required
def payments_today(request, location_slug):
    today = timezone.localtime(timezone.now())
    return HttpResponseRedirect(
        reverse(
            "location_payments",
            args=[],
            kwargs={
                "location_slug": location_slug,
                "year": today.year,
                "month": today.month,
            },
        )
    )


@login_required
def PeopleDaterangeQuery(request, location_slug):
    location = get_object_or_404(Location, slug=location_slug)
    start_str = request.POST.get("start_date")
    end_str = request.POST.get("end_date")
    s_month, s_day, s_year = start_str.split("/")
    e_month, e_day, e_year = end_str.split("/")
    start_date = datetime.date(int(s_year), int(s_month), int(s_day))
    end_date = datetime.date(int(e_year), int(e_month), int(e_day))
    bookings_for_daterange = (
        Booking.objects.filter(Q(status="confirmed"))
        .exclude(depart__lt=start_date)
        .exclude(arrive__gte=end_date)
    )
    recipients = []
    for r in bookings_for_daterange:
        recipients.append(r.user)
    residents = location.residents()
    recipients = recipients + list(residents)
    html = "<div class='btn btn-info disabled' id='recipient-list'>Your message will go to these people: "
    for person in recipients:
        info = (
            "<a class='link-light-color' href='/people/"
            + person.username
            + "'>"
            + person.first_name
            + " "
            + person.last_name
            + "</a>, "
        )
        html += info

    html = html.strip(", ")


def submit_payment(request, booking_uuid, location_slug):
    booking = Booking.objects.get(uuid=booking_uuid)
    location = get_object_or_404(Location, slug=location_slug)
    if request.method == "POST":
        form = PaymentForm(request.POST, default_amount=None)
        if form.is_valid():
            # account secret key
            stripe.api_key = settings.STRIPE_SECRET_KEY

            # get the payment details from the form
            token = request.POST.get("stripeToken")
            amount = float(request.POST.get("amount"))
            pay_name = request.POST.get("name")
            pay_email = request.POST.get("email")
            comment = request.POST.get("comment")

            pay_user = None
            try:
                pay_user = User.objects.filter(email=pay_email).first()
            except Exception:
                pass

            # create the charge on Stripe's servers - this will charge the user's card
            charge_descr = "payment from %s (%s)." % (pay_name, pay_email)
            if comment:
                charge_descr += " Comment added: %s" % comment
            try:
                charge = payment_gateway.stripe_charge_card_third_party(
                    booking, amount, token, charge_descr
                )

                # associate payment information with booking
                Payment.objects.create(
                    bill=booking.bill,
                    user=pay_user,
                    payment_service="Stripe",
                    payment_method=charge.source.brand,
                    paid_amount=(charge.amount / 100.00),
                    transaction_id=charge.id,
                    last4=charge.source.last4,
                )

                if booking.bill.total_owed() <= 0.0:
                    # if the booking is all paid up, do All the Things to confirm.
                    booking.confirm()
                    send_booking_receipt(booking, send_to=pay_email)

                    # XXX TODO need a way to check if this has already been sent :/
                    days_until_arrival = (
                        booking.use.arrive - datetime.date.today()
                    ).days
                    if (
                        days_until_arrival
                        <= booking.use.location.welcome_email_days_ahead
                    ):
                        guest_welcome(booking.use)
                    messages.add_message(
                        request,
                        messages.INFO,
                        "Thanks you for your payment! A receipt is being emailed to you at %s"
                        % pay_email,
                    )
                else:
                    messages.add_message(
                        request,
                        messages.INFO,
                        "Thanks you for your payment! There is now a pending amount due of $%.2f"
                        % booking.bill.total_owed(),
                    )
                    form = PaymentForm(default_amount=booking.bill.total_owed)

            except Exception as e:
                messages.add_message(
                    request,
                    messages.INFO,
                    "Drat, there was a problem with your card. Sometimes this reflects a card transaction limit, or bank "
                    + "hold due to an unusual charge. Please contact your bank or credit card, or try a different card. The "
                    + "error returned was: <em>%s</em>" % e,
                )
        else:
            logger.debug("payment form not valid")
            logger.debug(form.errors)

    else:
        form = PaymentForm(default_amount=booking.bill.total_owed)

    if booking.bill.total_owed() > 0.0:
        owed_color = "text-danger"
    else:
        owed_color = "text-success"
    return render(
        request,
        "payment.html",
        {
            "r": booking,
            "location": location,
            "total_owed_color": owed_color,
            "form": form,
            "stripe_publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
        },
    )


@resident_or_admin_required
def payments(request, location_slug, year, month):
    t0 = time.time()
    logger.debug("payments: timing begun:")
    location = get_object_or_404(Location, slug=location_slug)
    start, end, next_month, prev_month, month, year = occupancy.get_calendar_dates(
        month, year
    )

    summary_totals = {
        "gross_rent": 0,
        "net_rent_resident": 0,
        "gross_rent_transient": 0,
        "net_rent_transient": 0,
        "hotel_tax": 0,
        "hotel_tax_percent": 0.0,
        "res_external_txs_paid": 0,
        "res_external_txs_fees": 0,
        "all_subscriptions_net": 0,
        "taxed_subscription_gross": 0,
        "untaxed_subscription_net": 0,
        "taxed_subscription_user_fees": 0,
        "sub_external_txs_paid": 0,
        "sub_external_txs_fees": 0,
    }

    ##############################

    booking_totals = {
        "count": 0,
        "house_fees": 0,
        "to_house": 0,
        "non_house_fees": 0,
        "paid_amount": 0,
    }

    # JKS if the booking has bill line items that are not paid by the house
    # (so-called non_house_fees), then the amount to_house counts as transient
    # occupancy income. otherwise it counts as resident occupancy income.
    # TODO: we're essentially equating non house fees with hotel taxes. we
    # should make this explicit in some way.

    booking_payments_this_month = (
        Payment.objects.booking_payments_by_location(location)
        .filter(payment_date__gte=start, payment_date__lte=end)
        .order_by("payment_date")
        .reverse()
    )
    for p in booking_payments_this_month:
        # pull out the values we call multiple times to make this faster
        p_to_house = p.to_house()
        p_bill_non_house_fees = p.bill.non_house_fees()
        p_house_fees = p.house_fees()
        p_non_house_fees = p.non_house_fees()
        p_paid_amount = p.paid_amount

        summary_totals["gross_rent"] += p_to_house
        if p_bill_non_house_fees > 0:
            summary_totals["gross_rent_transient"] += p_to_house + p_house_fees
            summary_totals["net_rent_transient"] += p_to_house
            # XXX is p_non_house_fees == p_bill_non_house_fees??
            summary_totals["hotel_tax"] += p_non_house_fees
        else:
            summary_totals["net_rent_resident"] += p_to_house
        # track booking totals
        booking_totals["count"] = booking_totals["count"] + 1
        booking_totals["to_house"] = booking_totals["to_house"] + p_to_house
        booking_totals["non_house_fees"] = (
            booking_totals["non_house_fees"] + p_non_house_fees
        )
        booking_totals["house_fees"] = booking_totals["house_fees"] + p_house_fees
        booking_totals["paid_amount"] = booking_totals["paid_amount"] + p_paid_amount
        if p.transaction_id == "Manual":
            summary_totals["res_external_txs_paid"] += p_paid_amount
            summary_totals["res_external_txs_fees"] += p_house_fees

    not_paid_by_house = LocationFee.objects.filter(location=location).filter(
        fee__paid_by_house=False
    )
    for loc_fee in not_paid_by_house:
        summary_totals["hotel_tax_percent"] += loc_fee.fee.percentage * 100

    ##############################

    subscription_totals = {
        "count": 0,
        "house_fees": 0,
        "to_house": 0,
        "user_fees": 0,
        "total_paid": 0,  # the paid amount is to_house + user_fees + house_fees
    }

    subscription_payments_this_month = (
        Payment.objects.subscription_payments_by_location(location)
        .filter(payment_date__gte=start, payment_date__lte=end)
        .order_by("payment_date")
        .reverse()
    )
    # house fees are fees paid by the house
    # non house fees are fees passed on to the user
    for p in subscription_payments_this_month:
        # pull out the values we call multiple times to make this faster
        to_house = p.to_house()
        user_fees = (
            p.bill.non_house_fees()
        )  # p_bill_non_house_fees = p.bill.non_house_fees()
        house_fees = p.house_fees()  # p_house_fees = p.house_fees()
        total_paid = p.paid_amount

        summary_totals["all_subscriptions_net"] += to_house
        if user_fees > 0:
            # the gross value of subscriptions that were taxed/had user fees
            # applied are tracked as a separate line item for assistance with
            # later accounting
            summary_totals["taxed_subscription_gross"] += to_house + user_fees
            summary_totals["taxed_subscription_net"] += to_house
            summary_totals["taxed_subscription_user_fees"] += user_fees
        else:
            summary_totals["untaxed_subscription_net"] += to_house

        # track subscription totals
        subscription_totals["count"] = subscription_totals["count"] + 1
        subscription_totals["to_house"] = subscription_totals["to_house"] + to_house
        subscription_totals["user_fees"] = subscription_totals["user_fees"] + user_fees
        subscription_totals["house_fees"] = (
            subscription_totals["house_fees"] + house_fees
        )
        subscription_totals["total_paid"] = (
            subscription_totals["total_paid"] + total_paid
        )
        if p.transaction_id == "Manual":
            summary_totals["sub_external_txs_paid"] += total_paid
            summary_totals["sub_external_txs_fees"] += house_fees

    summary_totals["res_total_transfer"] = (
        summary_totals["gross_rent"]
        + summary_totals["hotel_tax"]
        - summary_totals["res_external_txs_paid"]
        - summary_totals["res_external_txs_fees"]
    )

    summary_totals["sub_total_transfer"] = (
        summary_totals["all_subscriptions_net"]
        + summary_totals["taxed_subscription_user_fees"]
        - summary_totals["sub_external_txs_paid"]
        - summary_totals["sub_external_txs_fees"]
    )

    summary_totals["total_transfer"] = (
        summary_totals["res_total_transfer"] + summary_totals["sub_total_transfer"]
    )
    summary_totals["gross_bookings"] = (
        summary_totals["gross_rent_transient"] + summary_totals["net_rent_resident"]
    )
    summary_totals["gross_subscriptions"] = (
        summary_totals["taxed_subscription_gross"]
        + summary_totals["untaxed_subscription_net"]
    )

    t1 = time.time()
    dt = t1 - t0
    logger.debug("payments: timing ended. time taken:")
    logger.debug(dt)
    return render(
        request,
        "payments.html",
        {
            "booking_payments": booking_payments_this_month,
            "summary_totals": summary_totals,
            "subscription_payments": subscription_payments_this_month,
            "subscription_totals": subscription_totals,
            "booking_totals": booking_totals,
            "location": location,
            "this_month": start,
            "previous_date": prev_month,
            "next_date": next_month,
        },
    )


@house_admin_required
def SubscriptionManageCreate(request, location_slug):
    if request.method == "POST":
        location = get_object_or_404(Location, slug=location_slug)
        notify = request.POST.get("email_announce")
        try:
            username = request.POST.get("username")
            subscription_user = User.objects.get(username=username)
        except Exception:
            messages.add_message(
                request,
                messages.INFO,
                "There is no user with the username %s" % username,
            )
            return HttpResponseRedirect(
                reverse("booking_manage_create", args=(location.slug,))
            )

        form = AdminSubscriptionForm(request.POST)
        if form.is_valid():
            subscription = form.save(commit=False)
            subscription.location = location
            subscription.user = subscription_user
            subscription.created_by = request.user
            subscription.save()
            subscription.generate_all_bills()
            if notify:
                admin_new_subscription_notify(subscription)
            messages.add_message(
                request,
                messages.INFO,
                "The subscription for %s %s was created."
                % (subscription.user.first_name, subscription.user.last_name),
            )
            return HttpResponseRedirect(
                reverse(
                    "subscription_manage_detail", args=(location.slug, subscription.id)
                )
            )
        else:
            logger.debug("the form had errors")
            logger.debug(form.errors)
            logger.debug(request.POST)

    else:
        form = AdminSubscriptionForm()
    all_users = User.objects.all().order_by("username")
    return render(
        request,
        "subscription_manage_create.html",
        {"form": form, "all_users": all_users},
    )


@house_admin_required
def SubscriptionsManageList(request, location_slug):
    location = get_object_or_404(Location, slug=location_slug)
    active = (
        Subscription.objects.active_subscriptions()
        .filter(location=location)
        .order_by("-start_date")
    )
    inactive = (
        Subscription.objects.inactive_subscriptions()
        .filter(location=location)
        .order_by("-end_date")
    )
    return render(
        request,
        "subscriptions_list.html",
        {"active": active, "inactive": inactive, "location": location},
    )


@house_admin_required
def SubscriptionManageDetail(request, location_slug, subscription_id):
    location = get_object_or_404(Location, slug=location_slug)
    subscription = get_object_or_404(Subscription, id=subscription_id)
    user = User.objects.get(username=subscription.user.username)
    domain = Site.objects.get_current().domain
    logger.debug("SubscriptionManageDetail:")

    email_forms = []
    email_templates_by_name = []

    emails = EmailTemplate.objects.filter(context="subscription")
    for email_template in emails:
        form = SubscriptionEmailTemplateForm(email_template, subscription, location)
        email_forms.append(form)
        email_templates_by_name.append(email_template.name)

    # Pull all the booking notes for this person
    if "note" in request.POST:
        note = request.POST["note"]
        if note:
            SubscriptionNote.objects.create(
                subscription=subscription, created_by=request.user, note=note
            )
            # The Right Thing is to do an HttpResponseRedirect after a form
            # submission, which clears the POST request data (even though we
            # are redirecting to the same view)
            subscription_note_notify(subscription)
            return HttpResponseRedirect(
                reverse(
                    "subscription_manage_detail", args=(location_slug, subscription_id)
                )
            )
    subscription_notes = SubscriptionNote.objects.filter(subscription=subscription)

    # Pull all the user notes for this person
    if "user_note" in request.POST:
        note = request.POST["user_note"]
        if note:
            UserNote.objects.create(user=user, created_by=request.user, note=note)
            # The Right Thing is to do an HttpResponseRedirect after a form submission
            return HttpResponseRedirect(
                reverse("subscription_manage_detail", args=(location_slug, booking_id))
            )
    user_notes = UserNote.objects.filter(user=user)

    return render(
        request,
        "subscription_manage.html",
        {
            "s": subscription,
            "user_notes": user_notes,
            "subscription_notes": subscription_notes,
            "email_forms": email_forms,
            "email_templates_by_name": email_templates_by_name,
            "domain": domain,
            "location": location,
        },
    )


@house_admin_required
def SubscriptionManageUpdateEndDate(request, location_slug, subscription_id):
    location = get_object_or_404(Location, slug=location_slug)
    subscription = Subscription.objects.get(id=subscription_id)
    logger.debug(request.POST)

    new_end_date = None  # an empty end date is an ongoing subscription.
    old_end_date = subscription.end_date
    if request.POST.get("end_date"):
        new_end_date = datetime.datetime.strptime(
            request.POST["end_date"], settings.DATE_FORMAT
        ).date()
        # disable setting the end date earlier than any recorded payments for associated bills (even partial payments)
        most_recent_paid = subscription.last_paid(include_partial=True)

        # careful, a subscription which has not had any bills generated yet
        # will have a paid_until value of None but is not problematic to change
        # the date.
        if most_recent_paid and new_end_date < most_recent_paid:
            messages.add_message(
                request,
                messages.INFO,
                "Error! This subscription already has payments past the requested end date. Please choose an end date after %s."
                % most_recent_paid.strftime("%B %d, %Y"),
            )
            return HttpResponseRedirect(
                reverse(
                    "subscription_manage_detail", args=(location_slug, subscription_id)
                )
            )

        if old_end_date and new_end_date == old_end_date:
            messages.add_message(
                request, messages.INFO, "The new end date was the same."
            )
            return HttpResponseRedirect(
                reverse(
                    "subscription_manage_detail", args=(location_slug, subscription_id)
                )
            )

    subscription.update_for_end_date(new_end_date)
    messages.add_message(request, messages.INFO, "Subscription end date updated.")
    return HttpResponseRedirect(
        reverse("subscription_manage_detail", args=(location_slug, subscription_id))
    )


@house_admin_required
def SubscriptionManageGenerateAllBills(request, location_slug, subscription_id):
    subscription = get_object_or_404(Subscription, pk=subscription_id)
    subscription.generate_all_bills()
    messages.add_message(
        request, messages.INFO, "Bills up to the current period were generated."
    )
    return HttpResponseRedirect(
        reverse("subscription_manage_detail", args=(location_slug, subscription.id))
    )
