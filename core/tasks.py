import csv
import io
import logging

from celery import shared_task
from django.db import transaction

from core.models import Dataset, DatasetRow

logger = logging.getLogger(__name__)

MAX_COLUMNS = 50
MAX_ROWS = 100_000
ROW_BATCH_SIZE = 500
MAX_CELL_SIZE = 1_000_000


class DatasetImportError(Exception):
    pass


@shared_task(name="core.process_dataset")
def process_dataset(dataset_id):
    """Validate a CSV and persist its rows for a campaign."""
    updated = Dataset.objects.filter(
        pk=dataset_id,
        status=Dataset.Status.QUEUED,
    ).update(status=Dataset.Status.PROCESSING, error_message="")
    if not updated:
        return {"dataset_id": dataset_id, "status": "not_queued"}

    dataset = Dataset.objects.get(pk=dataset_id)
    dataset.rows.all().delete()
    row_count = 0
    columns = []

    try:
        csv.field_size_limit(MAX_CELL_SIZE)
        with io.TextIOWrapper(
            dataset.file.open("rb"),
            encoding="utf-8-sig",
            newline="",
        ) as source:
            reader = csv.reader(source, strict=True)
            try:
                raw_columns = next(reader)
            except StopIteration as exc:
                raise DatasetImportError("This CSV is empty.") from exc

            columns = [column.strip() for column in raw_columns]
            if not columns or any(not column for column in columns):
                raise DatasetImportError("Every column needs a header.")
            if len(columns) > MAX_COLUMNS:
                raise DatasetImportError(
                    f"A CSV can have at most {MAX_COLUMNS} columns."
                )
            if len({column.casefold() for column in columns}) != len(columns):
                raise DatasetImportError("Column headers must be unique.")

            batch = []
            for row_number, values in enumerate(reader, start=2):
                if not values or not any(value.strip() for value in values):
                    continue
                if len(values) != len(columns):
                    raise DatasetImportError(
                        f"Row {row_number} has {len(values)} values; expected {len(columns)}."
                    )
                if row_count >= MAX_ROWS:
                    raise DatasetImportError(
                        f"A CSV can contain at most {MAX_ROWS:,} data rows."
                    )

                batch.append(
                    DatasetRow(
                        dataset=dataset,
                        row_number=row_number,
                        data=dict(zip(columns, values)),
                    )
                )
                row_count += 1
                if len(batch) >= ROW_BATCH_SIZE:
                    DatasetRow.objects.bulk_create(batch, batch_size=ROW_BATCH_SIZE)
                    batch.clear()

            if batch:
                DatasetRow.objects.bulk_create(batch, batch_size=ROW_BATCH_SIZE)

        if row_count == 0:
            raise DatasetImportError("Add at least one data row below the headers.")

    except (DatasetImportError, csv.Error, UnicodeDecodeError) as exc:
        dataset.rows.all().delete()
        dataset.status = Dataset.Status.FAILED
        dataset.row_count = 0
        dataset.columns = []
        dataset.error_message = str(exc)[:500]
        dataset.save(
            update_fields=("status", "row_count", "columns", "error_message", "updated_at")
        )
        return {"dataset_id": dataset_id, "status": "failed"}
    except Exception:
        logger.exception("Unexpected error while importing dataset %s", dataset_id)
        dataset.rows.all().delete()
        dataset.status = Dataset.Status.FAILED
        dataset.row_count = 0
        dataset.columns = []
        dataset.error_message = "We couldn't process this file. Check it is a valid UTF-8 CSV and try again."
        dataset.save(
            update_fields=("status", "row_count", "columns", "error_message", "updated_at")
        )
        return {"dataset_id": dataset_id, "status": "failed"}

    with transaction.atomic():
        Dataset.objects.filter(
            pk=dataset_id,
            status=Dataset.Status.PROCESSING,
        ).update(
            status=Dataset.Status.READY,
            columns=columns,
            row_count=row_count,
            error_message="",
        )

    return {"dataset_id": dataset_id, "status": "ready", "row_count": row_count}
