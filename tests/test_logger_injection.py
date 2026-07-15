import logging


class ListHandler(logging.Handler):
    """Sammelt Log-Records in einer Liste statt sie auszugeben."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def test_provider_logs_go_to_injected_logger_not_module_logger(make_provider, fake_sftp, environ):
    """Kernannahme des Multi-Tab-Feature: jede Verbindung bekommt ihren
    eigenen Logger, damit ihre Meldungen nur im eigenen Tab landen -
    unabhaengig davon, auf welchem Thread der Code tatsaechlich laeuft
    (z.B. cheroot-Worker-Threads bei echten WebDAV-Requests)."""
    tab_a_logger = logging.getLogger("connection.test-a")
    tab_a_logger.propagate = False
    tab_a_logger.setLevel(logging.DEBUG)
    handler_a = ListHandler()
    tab_a_logger.addHandler(handler_a)

    tab_b_logger = logging.getLogger("connection.test-b")
    tab_b_logger.propagate = False
    tab_b_logger.setLevel(logging.DEBUG)
    handler_b = ListHandler()
    tab_b_logger.addHandler(handler_b)

    try:
        provider_a = make_provider(logger=tab_a_logger)
        provider_b = make_provider(logger=tab_b_logger)
        try:
            provider_a.get_resource_inst("/", environ)
            provider_b.get_resource_inst("/", environ)

            messages_a = [r.getMessage() for r in handler_a.records]
            messages_b = [r.getMessage() for r in handler_b.records]

            assert any("get_resource_inst" in m for m in messages_a)
            assert any("get_resource_inst" in m for m in messages_b)

            # Kein Übersprechen zwischen den Tabs
            assert not any("connection.test-b" in r.name for r in handler_a.records)
            assert not any("connection.test-a" in r.name for r in handler_b.records)
        finally:
            provider_a.pool.close()
            provider_b.pool.close()
    finally:
        tab_a_logger.removeHandler(handler_a)
        tab_b_logger.removeHandler(handler_b)


def test_provider_without_logger_uses_module_default(make_provider, fake_sftp, environ):
    """Rückwärtskompatibilität: kein logger-Argument -> Modul-Logger wie bisher."""
    import webdav_sftp

    provider = make_provider()
    try:
        assert provider._logger is webdav_sftp._logger
        assert provider.pool._logger is webdav_sftp._logger
    finally:
        provider.pool.close()


def test_connection_pool_logs_go_to_injected_logger(make_provider, fake_sftp):
    custom_logger = logging.getLogger("connection.test-pool")
    custom_logger.setLevel(logging.DEBUG)
    handler = ListHandler()
    custom_logger.addHandler(handler)

    try:
        provider = make_provider(logger=custom_logger, pool_size=1)
        try:
            assert any("Initialisiere SFTP Connection Pool" in r.getMessage() for r in handler.records)
        finally:
            provider.pool.close()
    finally:
        custom_logger.removeHandler(handler)
