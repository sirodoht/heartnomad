# Generated by Django 5.0.6 on 2024-06-16 21:01

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_rename_customer_id_userprofile_stripe_customer_id_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="stripe_payment_method_id",
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
    ]
