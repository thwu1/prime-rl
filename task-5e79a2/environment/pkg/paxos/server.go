package paxos

import (
	"protoverify/pkg/base"
)

const (
	Propose = "propose"
	Accept  = "accept"
	Decide  = "decide"
)

type Proposer struct {
	N             int
	Phase         string
	N_a_max       int
	V             interface{}
	SuccessCount  int
	ResponseCount int
	Responses []bool
	SessionId int

	InitialValue interface{}
}

type ServerAttribute struct {
	peers []base.Address
	me    int

	n_p int
	n_a int
	v_a interface{}

	agreedValue interface{}

	proposer Proposer

	timeout *TimeoutTimer
}

type Server struct {
	base.CoreNode
	ServerAttribute
}

func NewServer(peers []base.Address, me int, proposedValue interface{}) *Server {
	response := make([]bool, len(peers))
	return &Server{
		CoreNode: base.CoreNode{},
		ServerAttribute: ServerAttribute{
			peers: peers,
			me:    me,
			proposer: Proposer{
				InitialValue: proposedValue,
				Responses:    response,
			},
			timeout: &TimeoutTimer{},
		},
	}
}

func (server *Server) MessageHandler(message base.Message) []base.Node {
	// TODO: Implement the Paxos message handler.
	// Must handle: ProposeRequest, ProposeResponse, AcceptRequest, AcceptResponse, DecideRequest.
	// Each node is immutable — return new node(s) reflecting possible outcomes.
	// For ProposeResponse/AcceptResponse: when the count reaches majority, return BOTH
	// a node that transitions to the next phase AND a node that stays in current phase counting.
	panic("implement me")
}

// To start a new round of Paxos.
func (server *Server) StartPropose() {
	// TODO: Initialize a new proposal round.
	// Increment N and SessionId, set phase to Propose, reset counters,
	// and broadcast ProposeRequest to all peers.
	panic("implement me")
}

func (server *Server) getNumber(address base.Address) int {
	for i := range server.peers {
		if server.peers[i] == address {
			return i
		}
	}
	return -1
}

func (server *Server) copy() *Server {
	response := make([]bool, len(server.peers))
	for i, flag := range server.proposer.Responses {
		response[i] = flag
	}

	var copyServer Server
	copyServer.me = server.me
	copyServer.peers = server.peers
	copyServer.n_a = server.n_a
	copyServer.n_p = server.n_p
	copyServer.v_a = server.v_a
	copyServer.agreedValue = server.agreedValue
	copyServer.proposer = Proposer{
		N:             server.proposer.N,
		Phase:         server.proposer.Phase,
		N_a_max:       server.proposer.N_a_max,
		V:             server.proposer.V,
		SuccessCount:  server.proposer.SuccessCount,
		ResponseCount: server.proposer.ResponseCount,
		Responses:     response,
		InitialValue:  server.proposer.InitialValue,
		SessionId:     server.proposer.SessionId,
	}

	copyServer.timeout = server.timeout

	return &copyServer
}

func (server *Server) NextTimer() base.Timer {
	return server.timeout
}

func (server *Server) TriggerTimer() []base.Node {
	if server.timeout == nil {
		return nil
	}

	subNode := server.copy()
	subNode.StartPropose()

	return []base.Node{subNode}
}

func (server *Server) Attribute() interface{} {
	return server.ServerAttribute
}

func (server *Server) Copy() base.Node {
	return server.copy()
}

func (server *Server) Hash() uint64 {
	return base.Hash("paxos", server.ServerAttribute)
}

func (server *Server) Equals(other base.Node) bool {
	otherServer, ok := other.(*Server)

	if !ok || server.me != otherServer.me ||
		server.n_p != otherServer.n_p || server.n_a != otherServer.n_a || server.v_a != otherServer.v_a ||
		(server.timeout == nil) != (otherServer.timeout == nil) {
		return false
	}

	if server.proposer.N != otherServer.proposer.N || server.proposer.V != otherServer.proposer.V ||
		server.proposer.N_a_max != otherServer.proposer.N_a_max || server.proposer.Phase != otherServer.proposer.Phase ||
		server.proposer.InitialValue != otherServer.proposer.InitialValue ||
		server.proposer.SuccessCount != otherServer.proposer.SuccessCount ||
		server.proposer.ResponseCount != otherServer.proposer.ResponseCount {
		return false
	}

	for i, response := range server.proposer.Responses {
		if response != otherServer.proposer.Responses[i] {
			return false
		}
	}

	return true
}

func (server *Server) Address() base.Address {
	return server.peers[server.me]
}
