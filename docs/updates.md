## Model Updates - Brief Cheat Sheet

If you update a model, create a migration and migrate.

Create the migration:

```sh
$ ./manage.py makemigrations
```

If you have a fixtures file, add/change field(s) to correspond to any model changes you
made, if necessary.

Then, as instructed, run:

```sh
$ ./manage.py migrate
```

If you want to sanity check things first, you can start by running the command with the
db-dry-run flag. Don't forget to run it for reals after:

```sh
$ ./manage.py migrate --dry-run
```

When you pull changes that include new migrations on a remote copy of the repo, run the
migrate command again:

```sh
$ ./manage.py migrate
```

For changes in where or what data is stored, use datamigrations:

1. create the new field (in the same or other model)
2. create a schemamigration for the new field (and optionally run it)
3. create a datamigration and customize the forward and backward functions
4. run the datamigration on a backup copy of the database
5. run it on the real version of the database
6. delete the old field
7. create a schemamigration to reflect the deleted field (as/if necessary)

Note for new models and permissions: to get the id for the permissions associated with a
model (there are 3 by default - add, change, delete), do the following:

```
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import Permission

[p.id for p in Permission.objects.filter(content_type=ContentType.objects.get(model="modelname"))]

# which will return a list, eg:
[40, 41, 42]
```

`modelname` is a string, the lowercase version of the model class name in your app's
models.py. Then add these to the list in appname/fixtures/initial_data.json, eg.:

```
[
    {
        "pk": 2,
        "model": "auth.group",
        "fields": {
            "name": "my_group",
            "permissions": [
                40,
                41,
                42,
            ]
        }
    },
    ...
]
```
