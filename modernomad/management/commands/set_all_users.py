import logging

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Set all users to given email, password and customer ID"
    args = "[email_address] [password] [customer_id]"
    requires_system_checks = True

    def handle(self, *labels, **options):
        if not labels or len(labels) < 1:
            raise CommandError("Args: <email_address> <password> <customer_id>")
        new_email_address = labels[0]
        logger.debug(f"Setting all emails:'{new_email_address}' ")
        new_password = None
        if len(labels) >= 2:
            new_password = labels[1]
            logger.debug(f"Setting all passwords:'{new_password}' ")
        new_customer_id = None
        if len(labels) >= 3:
            new_customer_id = labels[2]
            logger.debug(f"Setting all customer ids:'{new_customer_id}' ")

        changes = 0
        for u in User.objects.all():
            u.email = new_email_address
            if new_password:
                u.set_password(new_password)
            if new_customer_id:
                u.profile.stripe_customer_id = new_customer_id
            u.save()
            changes = changes + 1
        logger.debug(f"Changed {changes} users.")
