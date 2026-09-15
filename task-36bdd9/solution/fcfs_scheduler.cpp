
#include <vector>

#include "base/base.h"
#include "dram_controller/controller.h"
#include "dram_controller/scheduler.h"

namespace Ramulator {

class FCFS : public IScheduler, public Implementation {
  RAMULATOR_REGISTER_IMPLEMENTATION(IScheduler, FCFS, "FCFS", "Pure First-Come-First-Serve DRAM Scheduler.")
  private:
    IDRAM* m_dram;

  public:
    void init() override { };

    void setup(IFrontEnd* frontend, IMemorySystem* memory_system) override {
      m_dram = cast_parent<IDRAMController>()->m_dram;
    };

    ReqBuffer::iterator compare(ReqBuffer::iterator req1, ReqBuffer::iterator req2) override {
      // Pure FCFS: always select the request that arrived first.
      // Unlike FRFCFS, we do NOT check DRAM command readiness here.
      // The controller's schedule_request() handles readiness checking
      // after the scheduler picks the best candidate.
      if (req1->arrive <= req2->arrive) {
        return req1;
      } else {
        return req2;
      }
    }

    ReqBuffer::iterator get_best_request(ReqBuffer& buffer) override {
      if (buffer.size() == 0) {
        return buffer.end();
      }

      // Determine the prerequisite command for each request
      for (auto& req : buffer) {
        req.command = m_dram->get_preq_command(req.final_command, req.addr_vec);
      }

      // Find the earliest-arriving request (pure FCFS)
      auto candidate = buffer.begin();
      for (auto next = std::next(buffer.begin(), 1); next != buffer.end(); next++) {
        candidate = compare(candidate, next);
      }
      return candidate;
    }
};

}       // namespace Ramulator
