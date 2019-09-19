import voiplib
import sys

no_input = '--noi' in sys.argv
no_output = '--noo' in sys.argv

voiplib.Client(no_input=no_input, no_output=no_output).mainloop()
