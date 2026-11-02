"""A neighbouring GPU job. Same implementation as embedding_batch under another
ordinary name, so a process name never reveals whether a job is the fault."""
from .embedding_batch import main

if __name__ == "__main__":
    main()
