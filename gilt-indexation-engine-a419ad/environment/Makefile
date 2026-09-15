CXX = g++
CXXFLAGS = -std=c++17 -O2 -Wall

OBJS = main.o rpi.o schedule.o pricing.o

gilt_engine: $(OBJS)
	$(CXX) $(CXXFLAGS) -o $@ $^

main.o: main.cpp date_utils.h rpi.h schedule.h pricing.h analytics.h
	$(CXX) $(CXXFLAGS) -c main.cpp

rpi.o: rpi.cpp rpi.h date_utils.h
	$(CXX) $(CXXFLAGS) -c rpi.cpp

schedule.o: schedule.cpp schedule.h date_utils.h
	$(CXX) $(CXXFLAGS) -c schedule.cpp

pricing.o: pricing.cpp pricing.h rpi.h schedule.h date_utils.h
	$(CXX) $(CXXFLAGS) -c pricing.cpp

clean:
	rm -f gilt_engine *.o output.json

.PHONY: clean
