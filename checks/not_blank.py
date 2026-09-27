"""Exit 0 only if the frame has real contrast. A black or flat render is the
classic silent failure: the job 'succeeds' and the editor gets nothing."""
import sys

low, high = [int(float(v)) for v in sys.argv[1].split(",")[:2]]
sys.exit(0 if high - low > 5 else 1)
