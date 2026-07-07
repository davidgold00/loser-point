"""Raw data acquisition: MoneyPuck shot data, NHL API standings/schedules,
and a polite cached Hockey-Reference scraper for pre-2007 goal timestamps.

Every ingest function writes untouched raw artifacts to data/raw/ and never
transforms or drops rows — that responsibility belongs to validate/ and panel/.
"""
