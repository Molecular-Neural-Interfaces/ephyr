
class WrongSourceReaderError(Exception):
    def __init__(self, parser_class):
        super().__init__(f"Wrong source reader class: {parser_class}.")
